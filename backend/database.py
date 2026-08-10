import os
import json
import logging
import sqlite3
from collections.abc import Mapping
from urllib.parse import urlparse
from flask import current_app, g

logger = logging.getLogger(__name__)

_db_initialized = False


def is_vercel():
    return bool(os.environ.get("VERCEL"))


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


class PgCursor:
    def __init__(self, rows, columns, lastrowid=None, rowcount=0):
        self.rows = [PgRow(zip(columns, r)) for r in rows] if columns and rows else []
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
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = ()

        pg_sql = sql.replace("?", "%s")
        pg_sql = pg_sql.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        )
        # Timestamp columns are TEXT in this schema. PostgreSQL's CURRENT_TIMESTAMP
        # is timestamptz and has only an explicit cast to text, so literal usage
        # (DEFAULT ... and SET col = ...) fails on PG but not SQLite. Cast it so the
        # same SQL works on real PostgreSQL without changing the SQLite dev path.
        pg_sql = pg_sql.replace("CURRENT_TIMESTAMP", "(CURRENT_TIMESTAMP)::text")

        if (
            "PRAGMA table_info" in pg_sql
            or "PRAGMA journal_mode" in pg_sql
            or "PRAGMA synchronous" in pg_sql
        ):
            return PgCursor([], [], rowcount=0)

        is_insert = pg_sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in pg_sql.upper():
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
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    add_col_safe("users", "google_sub TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        job_description TEXT,
        overall_score INTEGER NOT NULL,
        dimension_scores TEXT NOT NULL,
        summary TEXT NOT NULL,
        strengths TEXT NOT NULL,
        weaknesses TEXT NOT NULL,
        missing_sections TEXT NOT NULL,
        ats_issues TEXT NOT NULL,
        suggestions TEXT NOT NULL,
        suggested_keywords TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    add_col_safe("analyses", "full_json TEXT")
    add_col_safe("analyses", "file_path TEXT")
    add_col_safe("analyses", "content_hash TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        analysis_json TEXT,
        data_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    add_col_safe("resumes", "filename TEXT")
    add_col_safe("resumes", "overall_score INTEGER DEFAULT 0")
    add_col_safe("resumes", "analysis_json TEXT")
    add_col_safe("resumes", "file_path TEXT")
    add_col_safe("resumes", "file_size INTEGER DEFAULT 0")
    add_col_safe("resumes", "mime_type TEXT DEFAULT 'application/pdf'")


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


def _connect_postgres(pg_url):
    import time
    import pg8000.dbapi

    parsed = urlparse(pg_url)

    last_err = None
    for attempt in range(3):
        try:
            conn = pg8000.dbapi.connect(
                user=parsed.username or "postgres",
                password=parsed.password or "",
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                database=parsed.path.lstrip("/") or "postgres",
                ssl_context=True,
                timeout=10,
            )
            return PgConnection(conn)
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
    }

    if pg_url:
        try:
            parsed = urlparse(pg_url)
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