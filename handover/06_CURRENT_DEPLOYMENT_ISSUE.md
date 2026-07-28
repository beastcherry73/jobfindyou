# Current Deployment Failure Analysis

This document details the diagnostic status of the `FUNCTION_INVOCATION_FAILED` crash on Vercel.

---

## 1. Symptoms & Traceback
- **HTTP Code**: 500 Internal Server Error
- **Header**: `X-Vercel-Error: FUNCTION_INVOCATION_FAILED`
- **Underlying Exception in Logs**:
  ```
  File "/var/task/app.py", line 1117, in <module>
    init_db()
  ...
  sqlite3.OperationalError: unable to open database file
  ```

---

## 2. Technical Explanation of the Crash

### A. The Import Sequence
1. Vercel routes a request to the serverless function `/api/index.py`.
2. The Vercel runtime boots up the python process and runs the entrypoint file `api/index.py`.
3. `api/index.py` executes `from app import app`.
4. This statement triggers the full compilation and execution of `app.py` from top to bottom.
5. In the deployed code (commit `ca10a2a`), the top-level contains a call to `init_db()`.
6. This function executes `sqlite3.connect(app.config["DATABASE"])`.
7. Because Vercel's hosting environment is read-only except for `/tmp`, and `app.config["DATABASE"]` is mapped to `resumeai.db` in the root workspace `/var/task`, SQLite attempts to create/write to `/var/task/resumeai.db`.
8. This results in the filesystem rejecting the write lock, crashing the process with `sqlite3.OperationalError` before Vercel can bind the application listener.

---

## 3. Investigated Hypotheses

### Hypothesis A: Vercel Is Stuck Deploying an Old Commit
- **Details**: The bug where `init_db()` was at the top level was fixed in local commits (moved to `__main__` or lazy initialized in `get_db()`), yet the Vercel logs still report the crash at line 1117 of `app.py`. Since line 1117 only exists in older revisions, Vercel is serving an old container build.
- **Confidence Level**: **High (99%)**
- **Validation**: Verified by analyzing the file length of `app.py` across different commits. Commit `ca10a2a` has exactly 1120 lines, where line 1117 calls `init_db()`. Current commits have over 1300 lines, showing that Vercel is not deploying the latest code.

### Hypothesis B: Missing Critical Environment Variables
- **Details**: The application is crashing during deployment because Vercel lacks variables like `SECRET_KEY` or `GROQ_API_KEY`, causing the app setup to behave unexpectedly or fallback paths to fail.
- **Confidence Level**: **Medium (50%)**
- **Validation**: If these variables are not configured in Vercel Project Settings, then even after the lazy database initialization fix is deployed, the application will crash when attempting to sign sessions or make Groq API calls.

### Hypothesis C: Build Configuration Errors
- **Details**: A bad configuration in `vercel.json` or `requirements.txt` (such as compiling native libraries like `libsql-client` or missing `python-dotenv`) has failed the build pipeline on Vercel, preventing newer commits from rolling out.
- **Confidence Level**: **High (90%)**
- **Validation**: Fixed by restoring `python-dotenv` to `requirements.txt` and ensuring `vercel.json` uses the standard array format.
