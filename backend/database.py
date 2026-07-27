import os
import json
import sqlite3
from collections.abc import Mapping
from flask import current_app, g

_db_initialized = False


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


def _create_tables_and_migrations(db):
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    try:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "google_sub" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
    except Exception as e:
        current_app.logger.warning(f"Migration error for users table: {e}")

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
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    )""")
    try:
        a_cols = {row["name"] for row in db.execute("PRAGMA table_info(analyses)")}
        if "full_json" not in a_cols:
            db.execute("ALTER TABLE analyses ADD COLUMN full_json TEXT")
    except Exception as e:
        current_app.logger.warning(f"Migration error for analyses table: {e}")


    db.execute("""CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    try:
        r_cols = {row["name"] for row in db.execute("PRAGMA table_info(resumes)")}
        if "filename" not in r_cols:
            db.execute("ALTER TABLE resumes ADD COLUMN filename TEXT")
        if "overall_score" not in r_cols:
            db.execute("ALTER TABLE resumes ADD COLUMN overall_score INTEGER DEFAULT 0")
        if "analysis_json" not in r_cols:
            db.execute("ALTER TABLE resumes ADD COLUMN analysis_json TEXT")
    except Exception as e:
        current_app.logger.warning(f"Migration error for resumes table: {e}")


def store_oauth_state(state):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO oauth_states (state) VALUES (?)",
            (state,)
        )
        db.commit()
    except Exception:
        pass


def verify_oauth_state(state):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id FROM oauth_states WHERE state = ?",
            (state,)
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
        db = get_db()
        db.execute(
            "DELETE FROM oauth_states WHERE created_at < datetime('now', '-15 minutes')"
        )
        db.commit()
    except Exception:
        pass


def get_db():
    global _db_initialized
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
                    current_app.logger.error(f"Error initializing Turso tables: {e}")
            return db
        except Exception as e:
            current_app.logger.warning(f"Turso connection failed, falling back to SQLite: {e}")

    if os.environ.get("VERCEL"):
        db_path = "/tmp/resumeai.db"
    else:
        db_path = current_app.config["DATABASE"]

    if not os.environ.get("VERCEL"):
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

    if not _db_initialized:
        try:
            _create_tables_and_migrations(db)
            db.commit()
            _db_initialized = True
        except Exception as e:
            current_app.logger.error(f"Error initializing SQLite tables: {e}")

    return db
