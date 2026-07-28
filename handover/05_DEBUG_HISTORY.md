# Chronological Debugging Log

This log chronicles all debugging attempts, changes made, and their outcomes during the search for a zero-crash Vercel deployment.

---

## Attempt 1: Moving Database Initialization to the Startup Block

### 1. Problem
Vercel serverless execution logs showed:
```
sqlite3.OperationalError: unable to open database file
```
The application was crashing during import because `init_db()` was called at the module level.

### 2. Hypothesis
Moving the `init_db()` call inside the `if __name__ == "__main__":` block would prevent Vercel from executing database logic during imports (since `__name__` is `"app"` when Vercel imports it).

### 3. Changes Made
- **File**: `app.py`
- **Code Modified**:
  - Removed top-level `init_db()` call.
  - Added `init_db()` inside `if __name__ == "__main__":`.

### 4. Outcome & Remaining Issue
- **Result**: The local commit `df2af13` was committed and pushed.
- **Remaining Issue**: The deployment did not update. The Vercel logs still reported the crash on line 1117 of `app.py`.

---

## Attempt 2: Changing vercel.json File Inclusion Syntax

### 1. Problem
Commit `2764448` had configured `"includeFiles"` as a string (`"templates/**,static/**"`) which is invalid in Vercel configuration.

### 2. Hypothesis
The invalid configuration prevented Vercel from building any commits after `ca10a2a`. Fixing it would allow Vercel to compile newer commits.

### 3. Changes Made
- **File**: `vercel.json`
- **Code Modified**:
  - Reverted `"includeFiles"` back to a JSON array format:
    ```json
    "includeFiles": ["templates/**", "static/**"]
    ```

### 4. Outcome & Remaining Issue
- **Result**: The commit `74278c4` was pushed.
- **Remaining Issue**: The deployment did not roll out the new code because another compilation issue was blocking the Vercel builder.

---

## Attempt 3: Removing Native Binary Dependency (`libsql-client`)

### 1. Problem
The local workspace uncommitted changes included `libsql-client` in `requirements.txt`. Native packages with C-extensions compile fine locally but cause build/link errors on AWS Lambda/Vercel.

### 2. Hypothesis
Removing `libsql-client` from `requirements.txt` would allow pip to build successfully on Vercel. `app.py` is already written to fallback to standard SQLite gracefully if the package is missing.

### 3. Changes Made
- **File**: `requirements.txt`
- **Code Modified**:
  - Removed `libsql-client` line.

### 4. Outcome & Remaining Issue
- **Result**: Commit `a899b2d` was committed and pushed.
- **Remaining Issue**: The build failed or still crashed with `FUNCTION_INVOCATION_FAILED`.

---

## Attempt 4: Fixing Missing `python-dotenv` Dependency

### 1. Problem
The file `app.py` imports `from dotenv import load_dotenv` at startup. However, `python-dotenv` was missing from `requirements.txt`.

### 2. Hypothesis
Without `python-dotenv`, the Vercel build would succeed in downloading requirements but crash immediately with `ModuleNotFoundError: No module named 'dotenv'` during module import.

### 3. Changes Made
- **File**: `requirements.txt`
- **Code Modified**:
  - Added `python-dotenv`.

### 4. Outcome & Remaining Issue
- **Result**: Commit `607462f` was pushed to GitHub.
- **Remaining Issue**: `FUNCTION_INVOCATION_FAILED` is still returned on the live website. This strongly indicates that the Vercel project deployment has either stalled, is deploying the wrong branch/folder, or lacks necessary environment variables like `SECRET_KEY` and `GROQ_API_KEY`.
