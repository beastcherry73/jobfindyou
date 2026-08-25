import os
import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from urllib.parse import urlparse
from flask import current_app, g

logger = logging.getLogger(__name__)

_db_initialized = False

# Schema migrations must run ONCE per database, not once per process/request.
# Vercel may run Python functions in one-shot processes that don't reuse module
# state, and _db_initialized (a process-local flag) can't survive that. So the
# PG path records a marker ROW in the database itself; any process can check it
# cheaply and skip the whole DDL suite when already applied. (The DDL suite is
# ~17 CREATE/ALTER statements; running it on every request costs 1-3s each.)
_SCHEMA_MARKER_KEY = "schema_version"
_SCHEMA_MARKER_VALUE = "3"


def is_vercel():
    return bool(os.environ.get("VERCEL"))


def safe_parse_db_url(url):
    """Parse a PostgreSQL connection URL without crashing on bracket-wrapped hosts.

    Python 3.11.4+ (Vercel runs 3.12) rejects a bracketed hostname that is not
    an IPv4/IPv6 literal, e.g. postgresql://u:p@[db.example.com]:5432/db, with
    ValueError from urllib.parse. Strip [ ] around non-IP hosts and retry.
    """
    try:
        return urlparse(url)
    except ValueError:
        cleaned = re.sub(r"\[([^\[\]]+)\]", r"\1", url)
        return urlparse(cleaned)


def get_required_db_url():
    """Return the PostgreSQL connection URL (SUPABASE_DB_URL or DATABASE_URL).

    In production (Vercel) this is REQUIRED. Absence is an application-level
    configuration error and must never silently fall back to SQLite.
    """
    pg_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if is_vercel():
        if not pg_url:
            raise RuntimeError(
                "DATABASE CONFIGURATION ERROR: Vercel production requires either "
                "SUPABASE_DB_URL or DATABASE_URL to be set to a PostgreSQL "
                "connection string. No SQLite fallback is permitted in production."
            )
        if not str(pg_url).startswith(("postgres://", "postgresql://")):
            raise RuntimeError(
                "DATABASE CONFIGURATION ERROR: SUPABASE_DB_URL/DATABASE_URL must be "
                "a PostgreSQL connection string starting with postgres:// or "
                "postgresql://. Got a value with a different scheme."
            )
    return pg_url


class LibsqlRow(Mapping):
    def __init__(self, row, columns):
        self._row = row
        self._columns = columns
        self._col_map = {name: i for i, name in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            if key in self._col_map:
                return self._row[self._col_map[key]]
            raise KeyError(f"Column '{key}' not found in row")
        return self._row[key]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._columns)

    def keys(self):
        return self._columns


class LibsqlCursor:
    def __init__(self, result_set):
        self.columns = result_set.columns
        self.rows = [LibsqlRow(row, self.columns) for row in result_set.rows]
        self._last_insert_rowid = result_set.last_insert_rowid
        self._index = 0

    @property
    def lastrowid(self):
        return self._last_insert_rowid

    def fetchone(self):
        if self._index < len(self.rows):
            row = self.rows[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        return self.rows


class LibsqlConnection:
    def __init__(self, client):
        self.client = client

    def execute(self, sql, parameters=None):
        if parameters is None:
            res = self.client.execute(sql)
        else:
            res = self.client.execute(sql, list(parameters))
        return LibsqlCursor(res)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SqliteConnection:
    """Thin wrapper around a dev-only SQLite connection.

    sqlite3.Connection's context manager commits/rolls back but does NOT close,
    which leaks the connection (and on Windows keeps the DB file locked, breaking
    tempdir cleanup in tests). This wrapper closes on context exit, mirroring
    PgConnection/LibsqlConnection. Never used in Vercel production.
    """

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, parameters=None):
        if parameters is None:
            return self.conn.execute(sql)
        return self.conn.execute(sql, parameters)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


class PgRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            keys = list(self.keys())
            return self[keys[key]]
        return super().__getitem__(key)


def pg_json_text(value):
    """Convert pg8000-decoded JSONB/JSON values (dict/list) back to their JSON
    text so callers that json.loads these columns behave identically to SQLite."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


class PgCursor:
    def __init__(self, rows, columns, lastrowid=None, rowcount=0):
        self.rows = [
            PgRow(zip(columns, (pg_json_text(v) for v in r)))
            for r in rows
        ] if columns and rows else []
        self._index = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._index < len(self.rows):
            row = self.rows[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        return self.rows


class PgConnection:
    def __init__(self, conn, pg_url=None):
        self.conn = conn
        self._pg_url = pg_url
        # Guards the SHARED socket so requests on the same warm instance can
        # never interleave statements/cursors (defense in depth; Vercel Python
        # normally serves one request at a time per instance).
        self._lock = threading.RLock()
        # Runtime (request-scope) lock for the shared connection is the SAME
        # object for every wrapper so reconnects keep one global serializer.
        self._runtime_lock = _PG_SHARED_RUNTIME_LOCK
        # Count of WRITE statements (INSERT/UPDATE/DELETE) executed in the
        # current transaction. If the shared socket is replaced (reconnect)
        # AFTER a write has already run in this transaction, those earlier
        # writes are gone; committing the retried statement alone would persist
        # a partial/orphaned row. `_reconnected_dirty` records that so commit()
        # aborts instead of silently saving a partial. Reset on commit/rollback.
        self._writes_in_txn = 0
        self._reconnected_dirty = False

    def _table_has_id(self, sql):
        import re

        m = re.search(r"INSERT\s+INTO\s+([^\s(]+)", sql, re.I | re.S)
        if not m:
            return False
        # Schema is defined entirely by our own migrations; only these tables
        # have a PRIMARY KEY that is NOT named `id`. Checking the set avoids an
        # information_schema query on every cold Vercel instance (~0.4s).
        return m.group(1).strip('"').lower() not in _PK_NOT_ID_TABLES

    def _run(self, sql, parameters):
        pg_sql = sql.replace("?", "%s")
        pg_sql = pg_sql.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        )

        if (
            "PRAGMA table_info" in pg_sql
            or "PRAGMA journal_mode" in pg_sql
            or "PRAGMA synchronous" in pg_sql
        ):
            return PgCursor([], [], rowcount=0)

        is_insert = pg_sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in pg_sql.upper() and self._table_has_id(pg_sql):
            pg_sql = pg_sql.rstrip(";") + " RETURNING id;"

        cur = self.conn.cursor()
        cur.execute(pg_sql, list(parameters))

        lastrowid = None
        rows = []
        cols = []

        if cur.description:
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            if is_insert and rows and "id" in cols:
                lastrowid = rows[0][cols.index("id")]

        return PgCursor(rows, cols, lastrowid=lastrowid, rowcount=cur.rowcount)

    @staticmethod
    def _is_write(sql):
        op = sql.lstrip()[:6].upper()
        return op.startswith(("INSERT", "UPDATE", "DELETE"))

    def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = ()
        with self._lock:
            is_write = self._is_write(sql)
            try:
                result = self._run(sql, parameters)
                if is_write:
                    self._writes_in_txn += 1
                return result
            except Exception as e:
                if _is_pg_recoverable(e):
                    # Recoverable: a stale shared connection (idle-dropped by the
                    # Supabase pooler, frozen serverless instance) or an aborted
                    # transaction left by an earlier failed statement on this
                    # SHARED connection. Roll back (or reconnect) and retry
                    # exactly once; statement-level atomicity guarantees the
                    # retry cannot double-effect.
                    had_prior_writes = self._writes_in_txn > 0
                    self._safe_rollback()
                    if had_prior_writes:
                        # Earlier writes in this transaction were discarded by the
                        # rollback/reconnect. Do NOT let commit() persist only the
                        # retried statement — mark the transaction poisoned so the
                        # caller gets an honest failure instead of a partial save.
                        self._reconnected_dirty = True
                    if _is_pg_conn_failure(e):
                        attempt = _pg_connect_reliable(self._pg_url)
                        self.conn = attempt.conn
                        # The reused socket is brand new; realign the shared TTL
                        # clock so the next request doesn't rotate immediately.
                        global _PG_SHARED_CREATED_AT
                        _PG_SHARED_CREATED_AT = time.monotonic()
                    result = self._run(sql, parameters)
                    # rollback() reset the counter; this retried statement now
                    # begins a fresh (implicit) transaction.
                    self._writes_in_txn = 1 if is_write else 0
                    return result
                # Non-recoverable SQL error (syntax, missing column, type
                # mismatch, etc.). Clear any aborted-txn state so later requests
                # on this shared connection still work, then surface the
                # original error.
                self._safe_rollback()
                raise

    def _safe_rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass
        self._writes_in_txn = 0

    def commit(self):
        # A real commit failure must NOT be swallowed — callers treat an
        # exception from commit() as "save failed".
        if self._reconnected_dirty:
            # The shared socket was replaced mid-transaction after one or more
            # writes had already run. Those writes are gone; committing now would
            # persist only the statements that ran after the reconnect (a partial
            # save / orphaned row). Discard and fail loudly so the caller retries.
            self._reconnected_dirty = False
            self._writes_in_txn = 0
            self._safe_rollback()
            raise RuntimeError(
                "Shared database connection was reset mid-transaction; aborting "
                "to avoid a partial save. Please retry."
            )
        self.conn.commit()
        self._writes_in_txn = 0

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass
        self._writes_in_txn = 0
        self._reconnected_dirty = False

    def close(self):
        # The PostgreSQL wrapper is a thin handle over the shared connection
        # (module-level cache). Closing the handle must NOT tear down the
        # underlying socket — that socket is reused across requests to avoid
        # paying a full TCP+TLS round trip to Supabase on every call.
        pass

    def _close_raw(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()
            try:
                # Release the request-scope lock acquired by get_db() so the
                # shared connection can serve the next request on this instance.
                self._runtime_lock.release()
            except Exception:
                pass


def _create_tables_and_migrations(db):
    is_pg = isinstance(db, PgConnection)

    def add_col_safe(table, col_def):
        try:
            if is_pg:
                db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_def}")
            else:
                col_name = col_def.split()[0]
                cols = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if col_name not in cols:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Migration error ({table}.{col_def}): {e}")

    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    add_col_safe("users", "google_sub TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        job_description TEXT,
        overall_score INTEGER NOT NULL,
        dimension_scores JSONB NOT NULL,
        summary TEXT NOT NULL,
        strengths JSONB NOT NULL,
        weaknesses JSONB NOT NULL,
        missing_sections JSONB NOT NULL,
        ats_issues JSONB NOT NULL,
        suggestions JSONB NOT NULL,
        suggested_keywords JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    add_col_safe("analyses", "full_json JSONB")
    add_col_safe("analyses", "file_path TEXT")
    add_col_safe("analyses", "content_hash TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS rate_limits (
        key TEXT NOT NULL,
        window_start INTEGER NOT NULL,
        hits INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (key, window_start)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS resumes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT,
        template TEXT NOT NULL DEFAULT 'modern',
        overall_score INTEGER DEFAULT 0,
        analysis_json JSONB,
        data_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    add_col_safe("resumes", "filename TEXT")
    add_col_safe("resumes", "overall_score INTEGER DEFAULT 0")
    add_col_safe("resumes", "analysis_json JSONB")
    add_col_safe("resumes", "file_path TEXT")
    add_col_safe("resumes", "file_size INTEGER DEFAULT 0")
    add_col_safe("resumes", "mime_type TEXT DEFAULT 'application/pdf'")

    db.execute("""CREATE TABLE IF NOT EXISTS jobs_tracker (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_title TEXT NOT NULL,
        company TEXT,
        location TEXT,
        listing_url TEXT,
        match_percent INTEGER,
        status TEXT NOT NULL DEFAULT 'Applied',
        applied_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    # Clicking Apply only opens the listing; it seeds a 'Viewed' row and stamps
    # viewed_date. applied_date is only meaningful once status leaves 'Viewed' —
    # set when the user self-reports the application (the return-to-tab
    # confirmation prompt, or the tracker's "Mark as Applied" action). We never
    # infer an application from the click itself. (applied_date keeps its
    # existing NOT NULL DEFAULT for backward compatibility; callers gate on
    # status rather than treating its insert-time placeholder as an apply time.)
    add_col_safe("jobs_tracker", "viewed_date TIMESTAMPTZ")

    if is_pg:
        db.execute(
            "CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT)"
        )
        db.execute(
            "INSERT INTO app_meta (meta_key, meta_value) VALUES (?, ?) "
            "ON CONFLICT (meta_key) DO UPDATE SET meta_value = excluded.meta_value",
            (_SCHEMA_MARKER_KEY, _SCHEMA_MARKER_VALUE),
        )
        db.commit()


def _pg_schema_up_to_date(db):
    """Cheap DB-persisted check that skips the DDL suite on already-migrated DBs.

    Uses a one-row marker table instead of a process-local flag so Vercel
    one-shot Python processes don't re-run all CREATE/ALTER statements."""
    try:
        # Single round trip: if the table/marker is missing the SELECT itself
        # raises (42P01/25P02) and we fall through to the full migration, which
        # CREATEs app_meta and writes the marker.
        row = db.execute(
            "SELECT meta_value FROM app_meta WHERE meta_key = ?",
            (_SCHEMA_MARKER_KEY,),
        ).fetchone()
        if row and row["meta_value"] == _SCHEMA_MARKER_VALUE:
            return True
    except Exception:
        return False
    return False


def store_oauth_state(state):
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO oauth_states (state) VALUES (?)",
                (state,),
            )
            db.commit()
    except Exception:
        pass


def verify_oauth_state(state):
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT id FROM oauth_states WHERE state = ?",
                (state,),
            ).fetchone()
            if row:
                db.execute("DELETE FROM oauth_states WHERE id = ?", (row["id"],))
                db.commit()
                return True
    except Exception:
        pass
    return False


def cleanup_expired_oauth_states():
    try:
        with get_db() as db:
            if isinstance(db, PgConnection):
                # PostgreSQL has no datetime() function; the SQLite form below
                # would raise (and be silently swallowed), so orphaned states —
                # from OAuth flows a user never completes — never got pruned.
                db.execute(
                    "DELETE FROM oauth_states "
                    "WHERE created_at < NOW() - INTERVAL '15 minutes'"
                )
            else:
                db.execute(
                    "DELETE FROM oauth_states "
                    "WHERE created_at < datetime('now', '-15 minutes')"
                )
            db.commit()
    except Exception:
        pass


_PG_SHARED_WRAPPER = None
_PG_SHARED_URL = None

# Serializes the SINGLE reused Supabase connection across whole request
# transactions. Vercel can run concurrent Python invocations on one warm
# instance; with a single shared connection, interleaved statement sets across
# two requests abort each other's transactions (25P02 / "in failed transaction
# block"). The lock is acquired in get_db() and released by PgConnection.__exit__,
# so at most one request uses the connection at a time per instance. Reentrant
# so nested get_db() blocks (e.g. oauth_state helpers) cannot deadlock.
_PG_SHARED_RUNTIME_LOCK = threading.RLock()

# Tables whose PRIMARY KEY is NOT named `id`. PgConnection appends
# RETURNING id to INSERTs (to surface lastrowid) only for tables NOT in this
# set. Enumeration is exact because the schema is defined entirely by our own
# migrations (users, analyses, resumes, oauth_states have id; app_meta and
# rate_limits do not). Kept as a constant to avoid an information_schema round
# trip on every cold Vercel instance.
_PK_NOT_ID_TABLES = frozenset({"app_meta", "rate_limits"})

# Maximum trusted lifetime for the reused Supabase connection. Supabase's
# connection pooler drops idle client sessions, so a socket older than this is
# rotated proactively in _connect_postgres (rather than waiting for the
# reconnect-on-error path). Reconnect cost is paid by at most one request per
# instance per TTL interval.
_PG_SHARED_CONN_TTL = 180.0
_PG_SHARED_CREATED_AT = 0.0


def _pg_connect_reliable(pg_url):
    """Open a single pg8000 connection (3 attempts). Returns the PgConnection."""
    import time
    import pg8000.dbapi

    parsed = safe_parse_db_url(pg_url)

    last_err = None
    for attempt in range(3):
        try:
            raw = pg8000.dbapi.connect(
                user=parsed.username or "postgres",
                password=parsed.password or "",
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                database=parsed.path.lstrip("/") or "postgres",
                ssl_context=True,
                timeout=10,
            )
            # Bound every server-side operation so a hung query on a half-open
            # socket can NEVER stall the whole warm instance (the shared
            # connection is serialized by a lock, so one stuck query would
            # otherwise block every other request until an OS TCP timeout). These
            # SET commands are committed so they become session defaults and are
            # not reverted by a later per-request rollback.
            try:
                sc = raw.cursor()
                sc.execute("SET statement_timeout = 20000")
                sc.execute("SET idle_in_transaction_session_timeout = 30000")
                raw.commit()
            except Exception:
                try:
                    raw.rollback()
                except Exception:
                    pass
            return PgConnection(raw, pg_url=pg_url)
        except Exception as e:
            last_err = e
            logger.warning(
                f"Supabase PostgreSQL connection attempt {attempt + 1}/3 failed: {e}"
            )
            if current_app:
                current_app.logger.warning(
                    f"Supabase PostgreSQL connection attempt {attempt + 1}/3 failed: {e}"
                )
            time.sleep(0.2 * (attempt + 1))

    raise RuntimeError(
        f"Database connection to Supabase PostgreSQL failed after 3 attempts: {last_err}"
    )


def _connect_postgres(pg_url):
    """Return a PostgreSQL connection, REUSING one connection across requests.

    On Vercel a module global survives across warm serverless invocations, so a
    single connection (and its established TCP/TLS session to Supabase) is shared
    by every request handled by the same instance. Without this, each API call
    pays a full connection handshake (measured at 3-6s/request in production),
    which is what made "Previous Analyses" appear empty/broken after a refresh.
    """
    global _PG_SHARED_WRAPPER, _PG_SHARED_URL, _PG_SHARED_CREATED_AT

    # Mutating the shared-connection globals (rotate/close/replace) MUST happen
    # under the same serializer that guards request transactions. Otherwise a
    # second concurrent invocation could close and replace the socket while the
    # first request is mid-transaction on it. get_db() already holds this lock
    # (RLock, so this reentrant re-acquire is free); db_diagnostic() does not,
    # so acquiring here also serializes the health endpoint against live traffic.
    with _PG_SHARED_RUNTIME_LOCK:
        if _PG_SHARED_WRAPPER is not None:
            if _PG_SHARED_URL == pg_url:
                # Supabase's connection pooler drops idle client sessions, after
                # which the cached socket is dead. Rotate proactively once the
                # connection is older than the trusted lifetime so a request
                # never depends on the reconnect-on-error path for a
                # systematically idle session. (Ignores a future timestamp to
                # stay correct across clock skew.) This is cheap: it triggers
                # once per instance per lifetime.
                ttl_passed = (time.monotonic() - _PG_SHARED_CREATED_AT) > _PG_SHARED_CONN_TTL
                if not ttl_passed:
                    return _PG_SHARED_WRAPPER
                try:
                    _PG_SHARED_WRAPPER._close_raw()
                except Exception:
                    pass
                _PG_SHARED_WRAPPER = None

        _PG_SHARED_WRAPPER = _pg_connect_reliable(pg_url)
        _PG_SHARED_URL = pg_url
        _PG_SHARED_CREATED_AT = time.monotonic()
        return _PG_SHARED_WRAPPER


def _is_pg_conn_failure(e):
    """True only for connection-level failures (never for SQL errors).

    SQL-level errors (syntax, missing column, datatype_mismatch, etc.) must
    propagate untouched — retrying those would double-execute and hide bugs.
    """
    try:
        import pg8000.exceptions as pg_exceptions

        if isinstance(e, pg_exceptions.InterfaceError):
            return True
        if isinstance(e, pg_exceptions.DatabaseError):
            st = getattr(e, "sqlstate", None) or ""
            if st.startswith("08"):
                return True
    except Exception:
        pass

    # Transport-layer failures. When the Supabase connection pooler drops a
    # long-idle client session, the next read on the SHARED socket raises an
    # OS-level/SSL error. The exact live message observed is
    # "cannot read from timed out object" (CPython ssl), which pg8000 surfaces
    # as a plain exception — NOT as pg8000.exceptions.InterfaceError — so it
    # must be classified here or the shared connection can never self-heal and
    # every request on that warm instance 500s until Vercel recycles it.
    try:
        import socket
        import ssl

        if isinstance(e, (OSError, ssl.SSLError)):
            return True
    except Exception:
        if isinstance(e, OSError):
            return True

    msg = str(e).lower()
    return any(
        k in msg
        for k in (
            "cannot read from timed out object",
            "read from timed out",
            "timed out object",
            "read timed out",
            "write timed out",
            "connection reset",
            "connection is closed",
            "connection lost",
            "connection refused",
            "server closed the connection",
            "server closed connection",
            "broken pipe",
            "socket",
            "ssl",
            "reported an error",
            "timeout expired",
        )
    )


def _is_pg_recoverable(e):
    """True when the SHARED connection can be safely retried after recovery.

    Connection failures (stale/recycled socket: 08xxx, InterfaceError) and an
    aborted transaction (25P02 — a leftover from an earlier failed statement on
    this shared connection) are transient: rollback (or reconnect) then retry.
    All other errors are genuine SQL failures and must NOT be retried.
    """
    if _is_pg_conn_failure(e):
        return True
    try:
        import pg8000.exceptions as pg_exceptions

        if isinstance(e, pg_exceptions.DatabaseError):
            if (getattr(e, "sqlstate", None) or "") == "25P02":
                return True
    except Exception:
        pass
    # Message fallback in case the aborted-transaction error ever surfaces
    # without proper sqlstate/type metadata (e.g. wrapped by another layer).
    msg = str(e).lower()
    return "current transaction is aborted" in msg or "25p02" in msg


def _connect_sqlite():
    """SQLite is ONLY for local development. Never called in Vercel production."""
    global _db_initialized

    assert not is_vercel(), (
        "SQLite is forbidden in Vercel production. get_db() must raise before "
        "reaching the SQLite branch."
    )

    db_path = current_app.config.get("DATABASE")
    if not db_path:
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resumeai.db"
        )
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except Exception:
        pass

    db = sqlite3.connect(db_path, timeout=30.0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass

    wrapped = SqliteConnection(db)
    if not _db_initialized:
        try:
            _create_tables_and_migrations(wrapped)
            wrapped.commit()
            _db_initialized = True
        except Exception as e:
            wrapped.close()
            if current_app:
                current_app.logger.error(f"Error initializing SQLite tables: {e}")
            raise

    return wrapped


def get_db():
    global _db_initialized

    # Production (Vercel) requires PostgreSQL. Missing/misconfigured/env is fatal.
    pg_url = get_required_db_url()

    if pg_url:
        # Acquire the shared serializer BEFORE touching the shared connection so
        # that acquisition, TTL rotation, reconnect, AND the caller's whole
        # transaction (through commit in PgConnection.__exit__) all run
        # single-threaded on the one reused socket. Acquiring after
        # _connect_postgres (the previous ordering) left a window where a second
        # concurrent invocation could rotate/replace the socket while the first
        # request was mid-transaction on it. Released in PgConnection.__exit__.
        _PG_SHARED_RUNTIME_LOCK.acquire()
        try:
            db = _connect_postgres(pg_url)
            if not _db_initialized:
                # Gate on a marker persisted in the DB. On a warm one-shot
                # Python process this re-runs the (cheap) marker check only;
                # on a freshly provisioned DB it runs the full DDL suite once.
                if isinstance(db, PgConnection) and not _pg_schema_up_to_date(db):
                    _create_tables_and_migrations(db)
                _db_initialized = True
        except Exception as e:
            try:
                _PG_SHARED_RUNTIME_LOCK.release()
            except Exception:
                pass
            if current_app:
                current_app.logger.error(f"Error initializing Pg tables: {e}")
            raise
        return db

    # Below here is LOCAL DEVELOPMENT ONLY (no VERCEL, no PostgreSQL configured).
    db_url = os.environ.get("TURSO_DATABASE_URL")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN")

    if db_url:
        try:
            import libsql_client

            client = libsql_client.create_client_sync(url=db_url, auth_token=auth_token or "")
            db = LibsqlConnection(client)
            if not _db_initialized:
                try:
                    _create_tables_and_migrations(db)
                    _db_initialized = True
                except Exception as e:
                    if current_app:
                        current_app.logger.error(f"Error initializing Turso tables: {e}")
                    raise
            return db
        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Turso connection failed, falling back to SQLite: {e}")

    return _connect_sqlite()


def _db_like_env_keys():
    """Safely report which environment keys look DB-related.

    Returns a list of {name, present, length} ONLY — never values. Used to spot
    a misnamed/mis-scoped Database URL var (e.g. a differing key name or a key
    holding an empty string) without leaking the variable's value.
    """
    keys = []
    for name in sorted(os.environ):
        upper = name.upper()
        if "URL" in upper and ("DATABASE" in upper or "SUPABASE" in upper or "POSTGRES" in upper or upper.endswith("_URL")):
            value = os.environ.get(name) or ""
            keys.append({"name": name, "present": bool(value), "length": len(value)})
    return keys


def db_diagnostic():
    """Safe diagnostic — never exposes secrets.

    Returns backend type, whether the required env var exists, and a host/project
    identifier derived from the parsed URL WITHOUT credentials. Connection strings
    and passwords are NEVER included.
    """
    pg_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    env_present = bool(pg_url)

    info = {
        "backend": None,
        "required_env_present": env_present,
        "host": None,
        "project": None,
        "mode": "production" if is_vercel() else "development",
        "config_ok": True,
        "vercel_env": os.environ.get("VERCEL_ENV"),
        "vercel_git_commit_sha": os.environ.get("VERCEL_GIT_COMMIT_SHA"),
        "db_like_env_keys": _db_like_env_keys(),
    }

    if pg_url:
        try:
            parsed = safe_parse_db_url(pg_url)
            info["scheme"] = parsed.scheme or "postgresql"
            info["host"] = parsed.hostname
            info["project"] = (parsed.path or "").lstrip("/").split("/")[0] or None
        except Exception:
            pass
        try:
            db = _connect_postgres(pg_url)
            db.close()
            info["backend"] = "PostgreSQL"
        except Exception as e:
            info["backend"] = "PostgreSQL (connection failed)"
            info["config_ok"] = False
            info["connection_error"] = f"{type(e).__name__}: {e}"
    elif is_vercel():
        info["backend"] = "MISCONFIGURED — no PostgreSQL env var (SQLite forbidden)"
        info["config_ok"] = False
    else:
        info["backend"] = "SQLite (local development only)"

    return info