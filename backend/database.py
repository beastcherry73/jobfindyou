import os
import json
import logging
import sqlite3
import re
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
_SCHEMA_MARKER_VALUE = "1"


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
        # Cache of {table_name: has_id_column} so lastrowid probing doesn't add
        # a round trip per INSERT. Survives reconnects (schema is per-database).
        self._id_col_cache = {}

    def _table_has_id(self, sql):
        import re

        m = re.search(r"INSERT\s+INTO\s+([^\s(]+)", sql, re.I | re.S)
        if not m:
            return False
        table = m.group(1).strip('"')
        table_lower = table.lower()
        if table_lower in self._id_col_cache:
            return self._id_col_cache[table_lower]
        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = 'id'",
                (table,),
            )
            has = cur.fetchone() is not None
        except Exception:
            # Can't probe → don't guess; skip RETURNING so the INSERT itself
            # never fails on an absent id column.
            has = False
        self._id_col_cache[table_lower] = has
        return has

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

    def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = ()
        try:
            return self._run(sql, parameters)
        except Exception as e:
            if _is_pg_recoverable(e):
                # Recoverable: either a stale shared connection (idle recycling,
                # frozen serverless instance) or an aborted transaction left by
                # an earlier failed statement on this SHARED connection. Roll
                # back (or reconnect) and retry exactly once; statement-level
                # atomicity guarantees the retry cannot double-effect.
                self._safe_rollback()
                if _is_pg_conn_failure(e):
                    attempt = _pg_connect_reliable(self._pg_url)
                    self.conn = attempt.conn
                return self._run(sql, parameters)
            # Non-recoverable SQL error (syntax, missing column, type mismatch,
            # etc.). Clear any aborted-txn state so later requests on this
            # shared connection still work, then surface the original error.
            self._safe_rollback()
            raise

    def _safe_rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

    def commit(self):
        # A real commit failure must NOT be swallowed — callers treat an
        # exception from commit() as "save failed".
        self.conn.commit()

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

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
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


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

    if is_pg:
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
        db.execute(
            "CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT)"
        )
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
            db.execute(
                "DELETE FROM oauth_states WHERE created_at < datetime('now', '-15 minutes')"
            )
            db.commit()
    except Exception:
        pass


_PG_SHARED_WRAPPER = None
_PG_SHARED_URL = None


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
    global _PG_SHARED_WRAPPER, _PG_SHARED_URL

    if _PG_SHARED_WRAPPER is not None:
        if _PG_SHARED_URL == pg_url:
            return _PG_SHARED_WRAPPER
        # Config changed (e.g. test switching env between runs) — rebuild.
        try:
            _PG_SHARED_WRAPPER._close_raw()
        except Exception:
            pass
        _PG_SHARED_WRAPPER = None

    _PG_SHARED_WRAPPER = _pg_connect_reliable(pg_url)
    _PG_SHARED_URL = pg_url
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
    msg = str(e).lower()
    return any(
        k in msg
        for k in (
            "socket",
            "connection is closed",
            "connection lost",
            "broken pipe",
            "server closed",
            "connection failed",
            "connection refused",
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
    return False


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
        db = _connect_postgres(pg_url)
        if not _db_initialized:
            try:
                # Gate on a marker persisted in the DB. On a warm one-shot
                # Python process this re-runs the (cheap) marker check only;
                # on a freshly provisioned DB it runs the full DDL suite once.
                if isinstance(db, PgConnection) and not _pg_schema_up_to_date(db):
                    _create_tables_and_migrations(db)
                _db_initialized = True
            except Exception as e:
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