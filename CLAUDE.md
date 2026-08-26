# CLAUDE.md

Handover notes for Claude Code working in this repository. Plain text, ASCII only.

Full detail lives in `PROJECT_HANDOVER.md` (404 lines). This file is the
condensed, readable version.

---

## 1. WHAT THIS PROJECT IS

JobSpike is a production web app ("AI Career OS") that:

- Takes a resume (PDF or TXT) + a job description
- Calls Groq (AI) to produce an ATS report
- Lets the user build a resume from the analysis
- Exports PDF / DOCX

Production URL: `https://www.jobspike.in`

Stack:

- Frontend: Flask templates (server-rendered) + vanilla JS SPA in
  `templates/workspace.html`. Chart.js radar charts.
- Backend: Flask (`app.py` -> `backend/__init__.py` `create_app()`), blueprints
  in `backend/routes/`, services in `backend/services/`.
- Database: PostgreSQL on Supabase (pooler). SQLite is DEV ONLY and forbidden
  in production (Vercel).
- AI: Groq, model fallback `openai/gpt-oss-120b` -> `openai/gpt-oss-20b`
  (updated 2026-08-23: the previous three models — `llama-3.3-70b-versatile`,
  `llama-3.1-8b-instant`, `gemma2-9b-it` — were all removed/decommissioned by
  Groq; verified via direct API calls. gpt-oss models require
  `reasoning_effort="low"` in the API call or they return empty content.)
- Deploy: Vercel (Python functions), auto-deploy from `origin/main`.

## 2. RULES FOR THE AGENT

1. NEVER print or commit secrets. Refer to env vars by NAME only
   (SUPABASE_DB_URL, GROQ_API_KEY, SECRET_KEY, etc.).
2. Never reintroduce SQLite fallback in production.
3. Never redesign the database schema without explicit approval.
4. Never make speculative production fixes. Require a captured traceback first.
5. Preserve user isolation (all queries scoped by user_id).
6. Preserve auth (Flask sessions, login_required, Google OAuth).
7. No permanent diagnostic endpoints. Temp probe routes must be removed.
8. To reproduce a production bug, hit the live site with a real account and
   capture the response body (the app renders `str(e)` in JSON `details` or in
   the HTML `Internal Server Error <p>...</p>`). Vercel Runtime Logs are not
   accessible without CLI auth.

## 3. MOST IMPORTANT FILE: backend/database.py

This is where all recent production fixes live. Read it before changing
anything.

- `get_required_db_url()` - returns the PG URL or raises in production.
- `PgConnection` - pg8000 wrapper. `execute()` runs `_run()`:
  - translates `?` -> `%s`
  - rewrites `INTEGER PRIMARY KEY AUTOINCREMENT` -> identity
  - appends `RETURNING id` only for tables that have an id column
    (`_PK_NOT_ID_TABLES = {"app_meta", "rate_limits"}`)
  - recovers transport errors and `25P02` (rollback -> reconnect once -> retry)
  - thread-locked with a per-socket RLock
- `_connect_postgres()` / `_pg_connect_reliable()` - ONE shared connection per
  instance, rotated every 180s (TTL). Supabase pooler drops idle sessions.
- `get_db()` - returns the shared wrapper and ACQUIRES the module-level
  `_PG_SHARED_RUNTIME_LOCK` (serializes concurrent requests).
- `PgConnection.__exit__` - commits and RELEASES the lock.
- `_is_pg_conn_failure` / `_is_pg_recoverable` - error classifier. Must classify
  OSError / ssl.SSLError / "cannot read from timed out object" / timeouts /
  resets / EOF / `25P02` as connection failures.
- `_create_tables_and_migrations(db)` - runtime DDL, runs once per database,
  gated by the `app_meta.schema_version` marker. BUMP `_SCHEMA_MARKER_VALUE`
  whenever you add a table/column, or live databases never run the new DDL.
  (Currently "4"; "4" added `ats_jobs`.)

Critical design: because the connection is SHARED and the lock serializes
requests, each `with get_db():` block must be short and self-contained.

## 4. OTHER IMPORTANT FILES

- `api/index.py` - Vercel entrypoint; renders startup exceptions as a plain
  text 500 so boot failures are visible.
- `backend/__init__.py` - `create_app()`, global error handler that surfaces
  `str(e)` (used to capture real production exceptions).
- `backend/routes/analysis.py` - `POST /api/analyze`, `GET /api/analyses`,
  `/api/analyses/<id>`, `/claim`. Save failure returns
  `500 {"error":"The analysis completed but could not be saved...","saved":false}`.
- `backend/routes/auth.py` - login/register/OAuth. NOTE: `login()` has no
  try/except, so DB errors bubble up as raw 500 (deliberate, aids diagnosis).
- `backend/routes/meta.py` - `GET /api/health`, `GET /api/health/db`
  (safe diagnostics; reports served commit SHA, never secrets).
- `backend/services/ats.py` - KEYLESS ATS JOB LAYER. Pulls jobs from employers'
  own public job boards (no API key at all) and searches our own copy. See
  section 12.
- `backend/data/ats_companies.json` - the verified company -> ATS registry
  (generated; do not hand-edit).
- `backend/services/jobsources.py` - multi-source dispatcher. Order: keyless ATS
  layer, then JSearch/Fantastic, then Adzuna/Careerjet/Jooble.
- `backend/services/ai.py` - Groq calls, model fallback on 429.
- `backend/services/ratelimit.py` - rate limiter, DB-backed, fails open.
- `backend/services/supabase_service.py` - private bucket upload, signed URLs.
- `migrations/001_supabase_schema.sql` - REFERENCE DDL only, not executed by
  the app. Runtime DDL in database.py is authoritative.
- `templates/workspace.html` - the SPA: `loadDashboard`, `loadHistory`
  (Previous Analyses section), `apiFetch`, upload modal, on-page error reporter.

## 5. DATABASE

Tables created at runtime by `_create_tables_and_migrations`:

- `users` - id identity PK, email UNIQUE, password_hash, google_sub, created_at
- `analyses` - id, user_id, filename, job_description, overall_score INT,
  dimension_scores/strengths/weaknesses/missing_sections/ats_issues/suggestions/
  suggested_keywords/full_json as JSONB, file_path, content_hash, created_at
- `resumes` - id, user_id, title, filename, template, overall_score,
  analysis_json/data_json JSONB, file_path, file_size, mime_type, created_at,
  updated_at
- `oauth_states` - state UNIQUE
- `rate_limits` - PK (key, window_start) - NO id column
- `ats_jobs` - id, fingerprint UNIQUE, platform, company_token, source_id,
  title, company, location, country_code, work_mode, employment_type,
  experience_level, salary_*, posted_at, apply_url, description, search_text,
  first_seen_at, last_seen_at. Synced from public employer job boards.
- `app_meta` - PK meta_key - NO id column, stores schema_version marker and the
  `ats_sync_cursor` (how far the last ATS sync pass got)

Adapter behavior to remember:

- JSONB columns come back as Python dict/list from pg8000; `pg_json_text()`
  converts them to JSON text so callers can `json.loads` uniformly.
- TIMESTAMPTZ is used; do NOT cast CURRENT_TIMESTAMP to ::text (broke real PG).

## 6. ANALYSIS FLOW (end to end)

1. POST /api/analyze (rate limited 10/300s)
2. Parse resume: PDF via pypdf, TXT via utf-8. Empty/scanned PDF -> 400.
3. Build prompt + call Groq (model fallback). GroqError -> 502.
4. clean_json -> json.loads -> normalize_analysis_dict
5. Optional upload to Supabase Storage (private bucket; failure only warns)
6. DB save (if user_id): dedupe by content_hash -> UPDATE or INSERT analyses,
   sync resumes row, commit. Any exception -> the "could not be saved" 500.
7. Response includes analysis JSON with id / resume_id.
8. UI "Previous Analyses" calls GET /api/analyses -> rows for user_id.

## 7. RECENT PRODUCTION BUGS AND FIXES (all verified)

1. No PG env var -> app would not boot on Vercel. Fixed: mandatory PG env,
   SQLite forbidden in production. (6f02e52)
2. Bracket-wrapped DB hostname broke Python urlparse. Fixed with
   `safe_parse_db_url()`. (1ada8e9)
3. TIMESTAMPTZ vs ::text mismatch broke DDL/UPDATEs on real PG. Fixed: use
   TIMESTAMPTZ, drop the cast. (4309f7f)
4. JSONB decoded to dict/list broke json.loads callers. Fixed: pg_json_text().
   (3d80569)
5. Shared connection + transaction issues ("Previous Analyses" empty, then
   intermittent 500s 42703/25P02). Fixed: one connection per instance, DDL once
   per DB, id-aware RETURNING, rollback+retry once on 25P02. (ed28112, 18acfe6,
   fc92a7a, 0c55b01)
6. Previous Analyses loading slow. Fixed: shared conn, single round trips.
   (d9689f7, f01bd9e)
7. Transport-error recovery (THE live bug). Live capture from POST /login 500
   body: `cannot read from timed out object`. Supabase pooler drops idle shared
   session; the SSL/OSError was not classified as a connection failure so the
   reconnect retry never ran, and every request on the warm instance 500'd.
   Fixed: classify OSError/ssl.SSLError + the observed messages, reconnect once,
   180s TTL. (2c73a08)
8. Concurrency: two live accounts hitting one warm instance interleaved
   statements on the shared connection -> `25P02 current transaction is aborted`
   and analyze "could not be saved" 500s. Fixed: module RLock in get_db()
   released in __exit__ serializes the shared socket. (6fb0463)

## 8. CURRENT GIT / DEPLOYMENT STATE

- HEAD: `6fb0463` (fix(prod): serialize the shared Supabase connection per request)
- Branch: main. Remote: https://github.com/beastcherry73/jobfindyou.git
- Working tree: clean (only this doc and PROJECT_HANDOVER.md are untracked,
  nothing committed)
- Live production commit (verified via GET /api/health/db):
  `6fb0463d547b44a1f4340501d71f0ee0de425e68`
- Pushing to main auto-deploys; ~1-3 min. Confirm served SHA after deploy via
  `/api/health/db` -> `vercel_git_commit_sha`.

## 9. TESTING

Suites to run before and after changes:

- `python scratch/test_production_safe.py` - 79/79
- `python scratch/test_sprint1_1_matrix.py` - 12/12
- `python scratch/test_export_fidelity.py` - 4 PASS
- `python scratch/test_ats_layer.py` - 67/67 (keyless ATS layer)

Then a real production E2E against jobspike.in with 2+ accounts (login,
analyses, analyze, refresh, detail, sequential AND concurrent).

E2E probe scripts live OUTSIDE the repo in the OS temp dir
(C:\Users\venut\AppData\Local\Temp\opencode\).

## 12. KEYLESS ATS JOB LAYER

Jobs pulled straight from employers' own public job boards. No API key, no
signup, no paid tier - and the stored `apply_url` is the employer's real
application page, not an aggregator redirect.

Seven platforms, each verified empirically against a live company board before
being built on:

    greenhouse  lever  ashby  smartrecruiters  workable  recruitee  breezy

Teamtailor was TESTED AND REJECTED: no public subdomain board (every
`{token}.teamtailor.com` returns 404) and its API needs a key plus a version
header. Do not re-add it to this tier.

Pipeline:

1. REGISTRY - `scratch/build_ats_registry.py` sweeps candidate company slugs
   (`scratch/ats_candidates.py`) against every platform's public endpoint and
   keeps only boards that actually answer with live jobs. It tests ALL
   platforms per candidate (no early exit) and verifies the board owner's name
   where the platform reports one. Output: `backend/data/ats_companies.json`.
2. SYNC - `ats.run_sync()` walks the registry from a cursor persisted in
   `app_meta.ats_sync_cursor`, fetching boards 8 at a time and upserting on the
   UNIQUE `fingerprint` (platform:token:source_id). Re-running NEVER duplicates.
   Triggered daily by the Vercel cron in vercel.json -> `/api/jobs/ats/sync`,
   which requires `Authorization: Bearer $CRON_SECRET` and refuses outright if
   CRON_SECRET is unset. Manual/local: `python scratch/sync_ats_jobs.py`.
3. SEARCH - `ats.search()` queries our own table, so every filter (work mode,
   experience level, employment type, salary, recency, keyword, exclude) is
   exact AND combinable. The aggregators each support only a subset, which is
   why the UI used to grey those filters out.
4. RANKING - ATS listings carry `apply_is_direct=True` and are merged ahead of
   Adzuna/Careerjet/Jooble, in the same tier as JSearch.

Cursor/pruning rules worth knowing:

- The cursor is written in the SAME transaction as each company's rows, so a
  sync killed by a serverless timeout resumes instead of restarting.
- A company's old rows are pruned only when its board returned a NON-EMPTY set;
  an empty board is indistinguishable from a failed fetch and must never
  trigger a delete.
- On a completed cycle: `prune_unregistered()` drops companies removed from the
  registry, then `prune_stale()` drops anything unseen for 21 days.
- `MAX_JOBS_PER_COMPANY = 300` stops one enterprise board (Bosch had ~4.8k)
  swamping the corpus.

Link health: `python scratch/verify_ats_registry.py --n 14` samples apply URLs
per platform; `--audit --prune` follows one URL per company and DROPS companies
whose destination is dead. It deliberately separates BLOCKED (403 bot
protection) and JS-SHELL (client-rendered page) from BROKEN, because those
links are intact - conflating them would wrongly delete working employers.

## 10. KNOWN RISKS

- Shared connection: a mid-request transport failure that reconnects can lose
  writes from statements before the reconnect. Mitigated by short single
  `with get_db()` blocks. Known, not yet redesigned.
- Groq can transiently 502 under rate limits (external, out of scope).
- POST /login surfaces raw 500 on DB outage (by design).
- Vercel Runtime Logs unavailable without CLI auth.
- 180s connection TTL is empirical (Supabase pooler idle timeout not verified).
- Google OAuth configured but full OAuth E2E not verified in this session.
- ATS layer: ~5% of jobs have no resolvable country (strings like "Distributed"
  or "Home based - Worldwide"); they are stored with country_code='' and so
  never match a country-filtered search. Deliberate under-reporting.
- ATS layer: a full sync pass is ~60s for 251 companies. If the Vercel plan
  caps function duration below that, the cron simply covers part of the
  registry and resumes next run - the corpus refreshes over a couple of days
  rather than daily. Raising maxDuration or cron frequency makes it truly
  daily.
- ATS layer: regional weighting is limited by reality, not effort. Indian, SEA
  and Middle East employers largely use Workday/Darwinbox/Keka/Naukri rather
  than these seven platforms, so 575 regional candidates yielded far fewer
  boards than the remote-friendly pool. Workday is the highest-value next
  platform (also keyless) if wider regional coverage is wanted.

## 11. WORKFLOW FOR THE NEXT AGENT

1. Read backend/database.py and git log BEFORE modifying anything.
2. Reproduce bugs against the live site; capture response bodies.
3. Get a real traceback before changing code (app error text if no logs).
4. Make the smallest fix; no schema/auth/frontend/Groq changes unless evidence
   demands it.
5. Run the three suites, then a live 2-account E2E including concurrent.
6. Verify the served commit SHA via /api/health/db.
7. Commit/push only after verification. Report commit SHA + served SHA.
