# Codex Handover Brief: Resume Analyzer (JobSpike)

This document is a comprehensive technical brief prepared specifically for OpenAI Codex (or any successor coding agent) to immediately take over development and debugging of the JobSpike repository with zero prior context.

---

## 1. Project Vision & Context
JobSpike is a candidate resume optimizer. It parses resumes, matches them against user-provided job descriptions, generates ATS scoring breakdowns, extracts keyword gaps, suggests passive-to-active bullet point rewrites, and enables users to modify and export their resumes.

- **Stack**: Python Flask, SQLite, Groq (Llama 3.3 70B model), Vanilla CSS, PyPDF, and Python-Docx.
- **Goal**: Establish a live, zero-crash production site at `https://www.jobspike.in` using Vercel Serverless Functions.

---

## 2. Architecture & File Reference

### Directory Map
- `/api/index.py`: Serverless WSGI entrypoint that hooks the Flask `app` object into Vercel's runtime wrapper.
- `/app.py`: Contains the entire backend system—routing, database connectivity, PDF reading, DOCX generation, and Groq API calls.
- `/vercel.json`: Handles routing rewrites (`/(.*) -> /api/index.py`) and asset bundling instructions (`includeFiles`).
- `/templates/` & `/static/`: Front-end components.

### Essential Design Decisions
- **Lazy Load Database Pattern**: To prevent serverless import crashes, the SQLite connection and schema creation are handled lazily inside `get_db()`.
- **WSGI Path Correction**: `api/index.py` adjusts `sys.path` dynamically before loading the Flask module to resolve Python importing pathways correctly in AWS Lambda.

---

## 3. Database Architecture & ephemerality
- **Local DB**: Standard SQLite `resumeai.db` or `jobfindyou.db`.
- **Vercel DB**: Evaluates to `/tmp/resumeai.db` on serverless execution.
- **Issue**: `/tmp` SQLite databases are ephemeral and get wiped when serverless containers recycle.
- **Turso Sync Fallback**: Code contains connection blocks for Turso Database URL and Auth Token. However, `libsql-client` has been removed from `requirements.txt` due to Vercel build conflicts (native Rust/C dependencies).

---

## 4. Current Deployment Crash & Troubleshooting History

### Diagnostic History
- **The Issue**: Vercel returns `500 FUNCTION_INVOCATION_FAILED`.
- **Traceback**:
  ```
  File "/var/task/app.py", line 1117, in <module>
    init_db()
  sqlite3.OperationalError: unable to open database file
  ```
- **Historical Analysis**:
  - The crash was caused by the top-level execution of `init_db()` during Flask module import.
  - While this was refactored locally, Vercel was stuck executing commit `ca10a2a` because subsequent deployments failed to build.
  - The build pipeline was blocked by:
    1. A format error in `vercel.json`'s `includeFiles` (using a comma-separated string instead of an array).
    2. A missing `python-dotenv` dependency in `requirements.txt` that triggered a `ModuleNotFoundError` on module loading.
  - Both issues have been fixed in the latest commit `607462f`.

---

## 5. Codex Tasks & Investigation Order

### Step 1: Verify the Active Build on Vercel
Log into the Vercel console and check the latest build history for the `jobfindyou` project.
- **If the build failed**: Check the logs to verify if it is a missing dependency or a syntax issue.
- **If the build succeeded but still crashes**: Confirm whether Vercel is deploying the correct branch (`main`) and verify that environment variables (`SECRET_KEY`, `GROQ_API_KEY`) are set.

### Step 2: Migrate to a Stateless Database
Replace SQLite fallback on Vercel with a remote PostgreSQL connection (e.g. Supabase or Neon) using the pure-Python driver `pg8000`.

### Step 3: Implement Google OAuth
Verify Google Client credentials in `client info.txt` and complete the integration of the `/auth/google` callback routes in `app.py`.
