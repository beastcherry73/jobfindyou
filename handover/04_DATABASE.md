# Database Schema & SQLite Reference

This document maps all database connections, variables, tables, and lazy initialization routines, as well as a proposed PostgreSQL migration path.

---

## 1. Database Variables & Functions Map in `app.py`

### A. Core Variables
- **`app.config["DATABASE"]` (Lines 23-26)**:
  - If running in a read-only environment (like Vercel serverless) or if the workspace directory is not writable, this is set to `/tmp/resumeai.db`.
  - Otherwise, it resolves to `resumeai.db` in the project root directory for local development.

### B. Core Functions
- **`_create_tables_and_migrations(db)` (Lines 398-446)**:
  - Self-contained function containing `CREATE TABLE IF NOT EXISTS` for `users`, `analyses`, and `resumes` tables.
  - Automatically runs safety migration checks (`PRAGMA table_info` and `ALTER TABLE`) to verify if critical columns like `google_sub` or `overall_score` exist, appending them if missing.
- **`get_db()` (Lines 448-489)**:
  - Lazily fetches the database connection.
  - **Turso Sync Fallback**: Checks if `TURSO_DATABASE_URL` is set in environment variables. If present, it attempts to import `libsql_client` and connect to the cloud database.
  - **SQLite Fallback**: If Turso environment variables are missing or connection fails, it opens a connection via `sqlite3.connect()`.
  - **Lazy Schema Creation**: Checks a global boolean `_db_initialized`. If `False`, it runs `_create_tables_and_migrations(db)` to construct the database schema on-demand and sets the flag to `True`.
- **`init_db()` (Lines 491-494)**:
  - Deprecated. Retained as a safe `pass` no-op to ensure compatibility with older execution layers.

---

## 2. Calls and Initialization Graph

```
[Request / Route Execution]
        │
        ▼
    get_db()
        │
        ├──► check: _db_initialized == False ?
        │               │
        │               ▼
        │        _create_tables_and_migrations(db)
        │        - CREATE TABLE IF NOT EXISTS users, analyses, resumes
        │        - ALTER TABLE check (PRAGMA table_info)
        │        - Set _db_initialized = True
        │
        ▼
    Return Connection (SQLite or Turso)
```

---

## 3. Future PostgreSQL Migration Plan
To support stateless, production-grade serverless functions without the limitations of transient local SQLite files or C-compiled SQL dependencies, we recommend migrating to **PostgreSQL** (e.g. Supabase or Neon):

1. **Add PostgreSQL Driver to `requirements.txt`**:
   - Add `pg8000` (a pure-Python PostgreSQL client that has **zero native C-dependencies** and builds flawlessly on Vercel) or `psycopg2-binary`.
2. **Modify Database Configuration in `app.py`**:
   - Retrieve `DATABASE_URL` from the environment.
   - Configure a connection pool or connection factory:
     ```python
     import pg8000
     def get_pg_db():
         db_url = os.environ.get("DATABASE_URL")
         # parse connection string and connect
         conn = pg8000.connect(...)
         return conn
     ```
3. **Adapt Query Syntax**:
   - Change SQLite parameter placeholder `?` to PostgreSQL format `%s` in all SQL queries inside `app.py`.
   - Adapt primary key declarations (`INTEGER PRIMARY KEY AUTOINCREMENT` -> `SERIAL PRIMARY KEY`).
