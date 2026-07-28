# Proposed Fixes for Deployment Issues

This document ranks the recommended fixes to address the Vercel deployment failure.

---

## Rank 1: Verify & Trigger Vercel Build Manually (Force Redeployment)

### 1. Explanation
The code modifications in the latest commit (`607462f`) have successfully resolved:
1. The top-level `init_db()` startup crash by introducing lazy SQLite table initialization in `get_db()`.
2. The missing `python-dotenv` dependency.
3. The correct array format of `includeFiles` in `vercel.json`.

If the site is still crashing with the old line 1117 error, it is because Vercel did not deploy this commit. A developer should log into the Vercel Dashboard, verify if the build for the latest commit failed or was skipped, and manually trigger a redeployment.

### 2. Details
- **Files Affected**: None (requires infrastructure actions).
- **Estimated Work**: 5 minutes.
- **Risk**: Very Low.
- **Confidence**: **99%**

---

## Rank 2: Check & Configure Vercel Project Environment Variables

### 1. Explanation
Stateless serverless containers require environment variables to function. Ensure that the Vercel Project has the following environment variables set in the dashboard:
- `SECRET_KEY`: A long random secret string.
- `GROQ_API_KEY`: API key for Llama 3.3.
- `GOOGLE_CLIENT_ID`: OAuth client id.
- `GOOGLE_CLIENT_SECRET`: OAuth secret.
- `GOOGLE_REDIRECT_URI`: Should be configured as `https://www.jobspike.in/auth/google/callback`.

### 2. Details
- **Files Affected**: None (configured in Vercel settings UI).
- **Estimated Work**: 5 minutes.
- **Risk**: Low.
- **Confidence**: **90%**

---

## Rank 3: Migrate to a Pure-Python Database Client (Supabase/Neon PostgreSQL)

### 1. Explanation
To bypass the limitations of ephemeral `/tmp` SQLite databases on serverless lambdas, migrate to a remote Postgres database (Supabase or Neon). Use a pure-Python driver like `pg8000` to guarantee zero compiled binary dependencies in `requirements.txt`.

### 2. Details
- **Files Affected**:
  - `requirements.txt` (add `pg8000`)
  - `app.py` (rewrite `get_db()` and parameter syntax `?` -> `%s`)
- **Estimated Work**: 2 hours.
- **Risk**: Medium (requires code modifications for SQL dialects).
- **Confidence**: **85%**
