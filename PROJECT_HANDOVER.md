# PROJECT HANDOVER — JobSpike (Resume Analyzer)

> **Documentation only.** This file describes the repository, its production
> architecture, known bugs and the current state. It was written for the next
> AI coding agent taking over this repository.
>
> **NEVER include actual secret values in any report.** Refer to environment
> variables by name only.

---

## 1. PROJECT OVERVIEW

**JobSpike** is a production web app ("AI Career OS") that analyzes a user's
resume against a job description, produces an ATS report, builds a resume, and
exports PDF/DOCX.

- **Frontend**: Server-rendered Flask templates + SPA behavior in
  `templates/workspace.html` (`index.html` guest marketing page, `auth.html`
  login/register, `generate.html`). Vanilla JS, Chart.js radar charts, fetch
  (`apiFetch`) + `<form>` based upload flows.
- **Backend**: Python Flask app (`app.py` → `backend/__init__.py`
  `create_app()`), blueprints under `backend/routes/`, services under
  `backend/services/`.
- **Database**: PostgreSQL on Supabase in production (`supabase/pooler`, AP
  Southeast). SQLite is development-only and explicitly forbidden in Vercel.
- **AI provider**: Groq (HTTP+SDK, `llama-3.3-70b-versatile` →
  `llama-3.1-8b-instant` → `gemma2-9b-it` fallback).
- **Deployment**: Vercel (Python functions), auto-deploy from `origin/main`.

---

## 2. CURRENT PRODUCTION ARCHITECTURE

- **Vercel**: `vercel.json` builds `api/index.py` with `@vercel/python`; catch-all
  route `/(.*)` → `api/index.py`. `api/index.py` bootstraps the Flask app and
  surfaces startup exceptions as a readable 500 body (`commit 5271fe1`).
- **Entrypoint**: `api/index.py` → `app` (`Flask` app from `create_app()`).
- **Supabase/PostgreSQL**: connection via pg8000 to a pooler host
  (`*.pooler.supabase.com`). One connection is **shared/reused** per running
  Vercel instance (see section 4).
- **Authentication**: Flask server-side sessions (signed cookie `session`,
  `HTTPOnly`, `SameSite=Lax`, `Secure` on Vercel). `login_required` decorator
  returns `401 {"error":"Please log in to use ResumeAI."}` for `/api/*`.
  Email/password (werkzeug hashing) + Google OAuth (state stored in DB).
- **Resume storage/processing**: upload → parse PDF (`pypdf`) or TXT →
  Optional upload to Supabase Storage (`resumes-private` bucket) → analysis.
- **Groq analysis flow**: prompt from `backend/prompts.py` → `ai.call_groq()`
  (model fallback on 429) → `helpers.clean_json()` → `normalize_analysis_dict()`.
- **Environment variables (names only — never values)**:
  `VERCEL`, `VERCEL_ENV`, `VERCEL_GIT_COMMIT_SHA`, `SUPABASE_DB_URL`,
  `DATABASE_URL`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_KEY` / `SUPABASE_ANON_KEY`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`,
  `GROQ_API_KEY`, `SECRET_KEY`.

### Mandatory production guard
- In Vercel, `get_required_db_url()` **raises** if neither `SUPABASE_DB_URL` nor
  `DATABASE_URL` (PostgreSQL) is configured.
- `_connect_sqlite()` has `assert not is_vercel()`. SQLite in production is a
  blocking error by design (commit `6f02e52`).
- `db_diagnostic()` (`GET /api/health/db`) reports only safe facts: backend,
  env-var presence/length, host, project, `vercel_env`, served commit SHA —
  **never secrets** (commits `13c30fa`, `6f02e52`).

---

## 3. IMPORTANT FILES

### `backend/database.py` — DB adapter + connection lifecycle (most critical)
- `safe_parse_db_url(url)` — parses PG URL; strips bracket-wrapped non-IP hosts
  that Python 3.11.4+ `urlparse` rejects (commit `1ada8e9`).
- `get_required_db_url()` — returns PG URL or raises in production.
- `PgConnection` — pg8000 wrapper. `execute()` runs `_run()` (translates `?`→`%s`,
  rewrites `INTEGER PRIMARY KEY AUTOINCREMENT` → identity, appends `RETURNING id`
  only for id-column tables via `_table_has_id()`), recovers transport/`25P02`
  errors (rollback → reconnect-once → retry), thread-locked.
- `PgCursor` / `PgRow` / `pg_json_text()` — row mapping; JSONB dict/list →
  JSON text (`commit 3d80569`).
- `_create_tables_and_migrations(db)` — runtime DDL (users, analyses,
  oauth_states, rate_limits, resumes, app_meta). Runs once per database; gated by
  the `app_meta.schema_version` marker (`_pg_schema_up_to_date`).
- `get_db()` — returns shared PG wrapper; acquires the request-scope
  `_PG_SHARED_RUNTIME_LOCK`.
- `_connect_postgres()` / `_pg_connect_reliable()` — shared-connection cache,
  180s TTL rotation.
- `_is_pg_conn_failure` / `_is_pg_recoverable` — error classifier (see bugs).
- SQLite (`SqliteConnection`) and Turso (`LibsqlConnection`) for dev only.
- Depends on: `pg8000`, Flask `g`/`current_app`.

### `api/index.py`
- Vercel entrypoint; imports `app`; renders boot errors as plain-text 500 so
  startup failures are visible in logs/response (commit `5271fe1`).

### `backend/__init__.py`
- `create_app()`: Flask app, error handlers. `@app.errorhandler(Exception)`
  returns `{"error": "An unexpected error...", "details": str(e)}` for `/api/*`;
  renders `Internal Server Error <p>{str(e)}</p>` for other paths (this is how
  the real production DB exceptions were captured without Vercel logs).
- Blueprints registered via `backend/routes/__init__.py`.

### `backend/routes/analysis.py`
- `analyze()` `POST /api/analyze` — full flow (parse → AI → save).
- `get_analyses()` `GET /api/analyses` (+`/claim`, `/api/analyses/<id>`
  GET/PUT/DELETE, `/signed-url`).
- JSONB `json.loads` handling for report reads.

### `backend/routes/auth.py`
- `register`/`login` (POST set session), `google_login`/`google_callback`,
  `logout`, `api/user/profile` GET/PUT.
- `login()` has **no try/except** — any DB error bubbles to the global handler
  (useful for diagnosis).

### `backend/routes/builder.py`
- Resume builder CRUD + auto-sync between `resumes`/`analyses`.

### `backend/routes/export.py`, `generate.py`
- PDF/DOCX export (reportlab, python-docx) with Builder preview fidelity
  (verified by `test_export_fidelity.py`).

### `backend/routes/meta.py`
- `GET /api/health`, `GET /api/health/db` (safe diagnostics). Holds currently
  NO diagnostic-injection endpoints (temp probe removed in `f301fdc`).

### `backend/routes/static.py`
- `index()` serves `workspace.html` when authenticated, else `index.html`.

### `backend/services/`
- `ai.py` — `call_groq()`, `GroqError` (fail-loud), model fallback loop.
- `helpers.py` — `extract_text_from_pdf`, `clean_json`, `normalize_analysis_dict`.
- `ratelimit.py` — `@rate_limit(...)` fixed-window, DB-backed, fails open.
- `supabase_service.py` — private bucket upload + signed URLs (env-gated).

### `backend/config.py`
- `configure_app()`: SECRET_KEY, DATABASE path, Google OAuth, session cookie
  flags, GROQ client, production DB env validation.

### `migrations/001_supabase_schema.sql`
- **Reference/manual** DDL for Supabase (users/resumes/analyses/
  schema_migrations/oauth_states, `updated_at` trigger, indexes).
- NOTE: the runtime (`database.py::_create_tables_and_migrations`) is the
  authoritative schema source; it creates the same core tables plus `rate_limits`
  and `app_meta`. The `.sql` file is not executed by the app.

### `templates/workspace.html`
- SPA: `loadDashboard` (recent history scrubs `#recentBody`), `loadHistory`
  (`data-section="history"`, `#historyBody`, `#historyCount`), `apiFetch`,
  upload modal + runAnalysis/uploadResume (AbortController), on-page error
  reporter (commits `1ad342a`, `a1920a8`).

### `vercel.json`, `requirements.txt`, `app.py`
- Vercel build config; pinned deps (commit `9c89ddf`); Flask WSGI entrypoint.

---

## 4. DATABASE

### Production schema (authoritative: `database.py::_create_tables_and_migrations`)
| Table | Key columns / types | Notes |
|---|---|---|
| `users` | `id` identity PK, `name` TEXT, `email` TEXT UNIQUE, `password_hash` TEXT, `google_sub` TEXT, `created_at` TIMESTAMPTZ | App users |
| `analyses` | `id`, `user_id`, `filename`, `job_description`, `overall_score` INT, `dimension_scores`/`strengths`/`weaknesses`/`missing_sections`/`ats_issues`/`suggestions`/`suggested_keywords`/`full_json` JSONB, `file_path`, `content_hash`, `created_at` | Report content |
| `resumes` | `id`, `user_id`, `title`, `filename`, `template`, `overall_score`, `analysis_json` JSONB, `data_json` JSONB, `file_path`, `file_size`, `mime_type`, `created_at`, `updated_at` | Builder data |
| `oauth_states` | `id`, `state` UNIQUE, `created_at` | Google OAuth |
| `rate_limits` | PK (`key`, `window_start`), `hits` | No `id` column |
| `app_meta` | PK `meta_key`, `meta_value` | No `id` column; stores `schema_version` marker |

`users`/`analyses`/`resumes` get indexes on `user_id`; `analyses` also on
`created_at`, `users.email` (see `.sql`).

### Type/adaptor behavior
- **JSONB**: `PgConnection._run` stores Python dicts as JSON text; reads convert
  JSONB (`dict`/`list`) back to JSON text via `pg_json_text()` so callers can
  `json.loads` uniformly with SQLite (commit `3d80569`).
- **TIMESTAMPTZ**: timestamps are stored TIMESTAMPTZ; the adapter no longer casts
  `CURRENT_TIMESTAMP` to `::text` (commits `4309f7f`, `3d80569`) — that cast
  caused `timestamptz`-into-`TEXT` mismatches on real PG.
- **`RETURNING id`**: appended only for INSERT targets that have an `id` column
  (`_PK_NOT_ID_TABLES = {"app_meta", "rate_limits"}`) — commit `0c55b01`.
- **`?`→`%s`** translation; `INTEGER PRIMARY KEY AUTOINCREMENT` →
  `BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`.

### Connection lifecycle (`backend/database.py`)
- ONE shared pg8000 connection per instance cached as `_PG_SHARED_WRAPPER`;
  `close()` is a no-op, `_close_raw()` for teardown.
- 180s TTL rotation in `_connect_postgres` (pooler drops idle sessions).
- Transport/`25P02` errors in `execute()` → `_safe_rollback()` → reconnect once
  → retry once.
- Per-request exclusive `_PG_SHARED_RUNTIME_LOCK` acquired in `get_db()`,
  released in `PgConnection.__exit__` — serializes concurrent requests on the
  shared socket.
- Statement-at-a-time autocommit-style usage: each `with get_db()` block commits
  in `__exit__`.

---

## 5. ANALYSIS FLOW (end-to-end)

1. **Upload** → `POST /api/analyze` (`analysis.py::analyze`), `@rate_limit(10/300s)`.
2. **Parse** → PDF: `helpers.extract_text_from_pdf` (pypdf); TXT: decode UTF-8.
   Empty/scanned PDF → 400 with guidance.
3. **Prompt + AI** → `ANALYSIS_PROMPT` + resumes[:12000] → `ai.call_groq()`
   (model fallback). `GroqError` → 502 "AI service is temporarily unavailable".
4. **Parse/normalize** → `clean_json` → `json.loads` → `normalize_analysis_dict`.
5. **Optional storage** → `supabase_service.upload_resume_to_storage` (private
   bucket; failure only warns).
6. **DB save** (`if user_id:` block) →
   - dedupe by `content_hash` → UPDATE or INSERT `analyses`;
   - sync `resumes` row (UPDATE or INSERT) with `data_json`;
   - `db.commit()`.
   - On ANY save exception → log `exc_info=True`, return
     `500 {"error":"The analysis completed but could not be saved...","saved":false}`
     (`analysis.py:183-193`).
7. **Response** → JSON analysis with `id`, `resume_id`; UI shows report.
8. **Previous Analyses** → `workspace.html::loadHistory` → calendar
   `GET /api/analyses` (`analysis.py:319-331`) → rows for `user_id` →
   `#historyBody`/`#historyCount`.

---

## 6. RECENT PRODUCTION BUGS AND FIXES (actual, verified)

1. **Supabase URL configuration issue** — app crashed at startup in Vercel
   because a PostgreSQL URL env var was missing/mis-scoped; startup blocker
   added. `6f02e52`, `5a42804`.
   - Symptom: boot failure on Vercel; no database.
   - Root cause: no `SUPABASE_DB_URL`/`DATABASE_URL` and no forced-PG guard.
   - Fix: mandatory PG env in `get_required_db_url()`; SQLite forbidden in
     Vercel; safe `db_diagnostic()`.
   - Evidence: `GET /api/health/db` reports `required_env_present`.

2. **Bracket-wrapped PostgreSQL hostname / Python `urlparse`** — `1ada8e9`.
   - Symptom: `ValueError` from `urllib.parse` on `[db.example.com]` bracketed
     hosts → Flask failed to start on Python 3.12.
   - Root cause: Python 3.11.4+ rejects non-IP bracket hosts.
   - Fix: `safe_parse_db_url()` strips `[ ]` around non-IP hosts and retries.

3. **TIMESTAMPTZ vs `::text`** — `4309f7f`, `3d80569`.
   - Symptom: schema DDL / UPDATEs failed on real PG (`timestamptz` vs `TEXT`
     mismatch) while silently "working" on SQLite.
   - Root cause: adapter cast `CURRENT_TIMESTAMP` to `::text` into TEXT columns.
   - Fix: use TIMESTAMPTZ, drop the `::text` cast.

4. **JSONB decoding** — `3d80569`.
   - Symptom: JSONB columns returned as Python `dict`/`list`, breaking `json.loads`
     callers / responses.
   - Root cause: pg8000 decodes JSONB into objects; SQLite path yields text.
   - Fix: `pg_json_text()` normalizes to JSON text on read.

5. **Shared PostgreSQL connection / transaction issue** — `ed28112`, `18acfe6`,
   `fc92a7a`, `0c55b01`.
   - Symptom: after refresh, "Previous Analyses" stale/empty; later `POST /login`
     and `/api/analyses` intermittently 500 with `42703` / `25P02`.
   - Root cause: one connection per request paid 3-6s handshakes + DDL re-ran
     per request; then a single cached connection carried aborted transactions
     and `INSERT … RETURNING id` failed on id-less tables.
   - Fix: reuse one connection; run DDL once per DB (`app_meta` marker);
     id-aware `RETURNING`; rollback + retry once on `25P02`.
   - Evidence: timing drops (analyses ~4s → ~0.7s warm); suites green.

6. **Previous Analyses loading** — `ed28112`, `18acfe6`, `d9689f7`, `f01bd9e`.
   - Symptom: section stayed "Loading…"/empty ~9s after refresh.
   - Root cause: per-request connection + DDL cost.
   - Fix: shared connection, single `information_schema`/marker round trips,
     exact `_PK_NOT_ID_TABLES`.
   - Evidence: browser E2E populated rows in ~0s (warm).

7. **Transport-error recovery** — `2c73a08`.
   - Symptom (live, captured server-side): every request on a warm instance
     500'd with
     `cannot read from timed out object` (login body) until platform recycled it.
   - Root cause (PROVEN via live body): Supabase pooler drops the idle shared
     session; next read raises a CPython SSL/OSError that
     `_is_pg_conn_failure` did not classify (not pg8000 InterfaceError / 08xxx),
     so the reconnect-once retry never ran.
   - Fix: classify `OSError`/`ssl.SSLError` and observed messages
     (`cannot read from timed out object`, timeouts, resets, EOF, `25P02`),
     reconnect+retry once; 180s shared-connection TTL.
   - Evidence: captured 500 bodies; classifier unit test; E2E.

8. **Per-request serialization** — `6fb0463`.
   - Symptom (live E2E, concurrent): `GET /api/analyses` →
     `25P02 current transaction is aborted` and `in failed transaction block`;
     `POST /api/analyze` → 500 `saved:false` — across MULTIPLE user accounts.
   - Root cause (PROVEN): Vercel runs concurrent Python invocations on one warm
     instance; overlapping requests interleaved statement sets on the single
     shared connection, aborting each other's transactions.
   - Fix: module `RLock` acquired in `get_db()`, released in
     `PgConnection.__exit__` — serializes the shared socket per request.
   - Evidence: sequential 2-account E2E pass; concurrent 8-thread save+read
     stress 24/24 clean; zero 25P02 after fix.

**Other relevant:** temp diagnostic route `/api/_tmp/db_probe` was added
(`087585f`) and removed (`f301fdc`) — do not reintroduce permanent diagnostics.

---

## 7. CURRENT GIT STATE

- **HEAD**: `6fb0463` `fix(prod): serialize the shared Supabase connection per request`
- **Remote**: `origin` = `https://github.com/beastcherry73/jobfindyou.git`, branch `main`
- **Working tree**: clean
- Recent commits (newest first):
  `6fb0463`, `2c73a08`, `f301fdc`, `f01bd9e`, `d9689f7`, `0c55b01`, `fc92a7a`,
  `18acfe6`, `087585f`, `ed28112`, `3d80569`, `1ada8e9`, `5271fe1`, `9c89ddf`,
  `13c30fa`, `4309f7f`, `6f02e52`.

---

## 8. CURRENT DEPLOYMENT STATE

- **Vercel project**: JobSpike; GitHub repo `beastcherry73/jobfindyou` (auto-deploy
  from `main`).
- **Production domain**: `https://www.jobspike.in`.
- **Known production commit (verified via `GET /api/health/db →
  vercel_git_commit_sha`)**: `6fb0463d547b44a1f4340501d71f0ee0de425e68`
- **Deployment ID**: NOT VERIFIED (no Vercel CLI token in this environment).
- **Config**: `vercel.json` ({version:2, build api/index.py @vercel/python,
  catch-all route}). Requirements pinned (`9c89ddf`).
- **Caveats**:
  - Pushing to `main` triggers a Production deploy; new instances can take
    ~1–3 min to serve.
  - Health endpoint reports the served SHA — always confirm it after deploy.
  - Vercel Runtime Logs were unreachable from this machine (CLI logged out, no
    token). Do not rely on logs unless you can authenticate.

---

## 9. TESTING

| Suite | Command | What it verifies |
|---|---|---|
| Full suite | `python scratch/test_production_safe.py` | **79/79** — production-safe persistence, auth/envelope, connection guard, save semantics, adapter behaviors |
| Sprint matrix | `python scratch/test_sprint1_1_matrix.py` | **12/12** — 12 persistence & export acceptance criteria |
| Export fidelity | `python scratch/test_export_fidelity.py` | **4 PASS** — multi-page PDF, PDF multi-page flow, DOCX, XML/HTML escaping |
| Classifier | `opencode/temp test_classifier.py` | transport-vs-SQL error classification (incl. `cannot read from timed out object`, `25P02`) |
| Prod E2E | scripts in OS temp dir (`C:\Users\venut\AppData\Local\Temp\opencode\`) | 2-account sequential full flow (login→analyses→analyze saved→Previous Analyses→refresh→detail); concurrent analyze; concurrency stress (8 threads × save/read = 24/24 clean) |

E2E/concurrency probe scripts live **outside the repo** in the OS temp dir
(`browserrepro-venv`, `e2e_full.py`, `conc_stress.py`, etc.) — not part of the
repository.

---

## 10. KNOWN ISSUES / RISKS

KNOWN (verified in this repo/session):
- Shared-connection design: a mid-request transport failure that reconnects can,
  in a rare multi-statement block, lose writes from statements executed before
  the reconnect (the earlier connection's transaction cannot be replayed on the
  new one). Mitigated by discovery+save being single-`with` blocks, but is an
  inherent edge. NOT yet redesign-mitigated.
- Concurrent Groq calls can return transient `502 AI service is temporarily
  unavailable` under provider rate limits (seen once in concurrent E2E). This is
  external (Groq) and by scope "do not change".
- `POST /login` has no try/except; DB outages surface as raw 500 (by design,
  aids diagnosis).
- Vercel Runtime Logs: NOT VERIFIED / unavailable without CLI auth.
- Supabase pooler idle-timeout value: NOT VERIFIED; the 180s TTL is empirical.
- Vercel concurrent-invocation semantics: the overlap was **observed** in E2E;
  platform guarantee NOT VERIFIED.
- Google OAuth: configured; full OAuth E2E NOT VERIFIED in this session.
- `migrations/001_supabase_schema.sql` is reference-only; runtime DDL is in
  `database.py`. Keeping them aligned is manual.

---

## 11. DO NOT BREAK THESE

- Do not reintroduce SQLite fallback in production (guard in
  `get_required_db_url`/`_connect_sqlite`).
- Do not expose secrets / print connection strings or passwords (incl. in logs
  and reports).
- Do not change the database architecture/redesign tables without explicit
  approval.
- Do not blindly redeploy old Vercel deployments.
- Do not make speculative production fixes — require a captured traceback.
- Preserve user isolation (all reads/writes scoped by `user_id`).
- Preserve existing authentication (Flask session, `login_required`,
  Register/Google OAuth).
- Preserve the production-only-PostgreSQL guard and per-request serialization
  of the shared connection.

---

## 12. HANDOVER INSTRUCTIONS (checklist for the next agent)

1. **Inspect before modifying** — read `backend/database.py`, the route files,
   and `git log` first. Never "fix" without understanding the shared-connection
   lifecycle.
2. **Reproduce production bugs** — against `https://www.jobspike.in` using
   real accounts; capture the server response bodies (the app's `str(e)` in
   `{"details": ...}` or the HTML `Internal Server Error <p>{str(e)}</p>`).
3. **Obtain the actual traceback** — Runtime Logs need Vercel CLI auth; if
   unavailable, capture the application's own error text before changing code.
4. **Make the smallest fix** — no schema/auth/frontend/Groq changes unless the
   evidence demands it; no permanent diagnostic endpoints.
5. **Run tests** — `test_production_safe.py` (79), `test_sprint1_1_matrix.py`
   (12), `test_export_fidelity.py` (4). Then a real production E2E (2+ accounts)
   including refresh + detail + sequential and concurrent requests.
6. **Verify production** — confirm the served `vercel_git_commit_sha` via
   `/api/health/db` before and after; repeat E2E against the new deployment.
7. **Commit/push only after verification** — then report the exact commit SHA
   and the served SHA.