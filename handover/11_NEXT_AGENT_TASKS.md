# Next Steps & Recommended Action Plan

This document lists prioritized actions for the next software engineer or coding agent.

---

## Task 1: Force Redeployment on Vercel
- **Priority**: High (Must be done first)
- **Difficulty**: Easy
- **Blockers**: Needs access to the Vercel Dashboard for `beastcherry73`'s account.
- **Description**:
  Ensure Vercel builds the latest commit (`607462f`). Check build logs in the Vercel console to confirm if the build completes and dependencies install successfully.

---

## Task 2: Validate Environment Variables on Production
- **Priority**: High
- **Difficulty**: Easy
- **Blockers**: Needs project credentials.
- **Description**:
  Check if `SECRET_KEY`, `GROQ_API_KEY`, `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET` are correctly configured in Vercel.

---

## Task 3: Establish a Persistent Database (Option A: Supabase / Option B: Turso)
- **Priority**: Medium
- **Difficulty**: Medium
- **Blockers**: Ephemeral `/tmp/resumeai.db` SQLite database is wiped on container recycle. Needs a cloud database connection to retain user registration data.
- **Description**:
  - Connect a Supabase PostgreSQL instance using `pg8000` (pure Python, zero C dependencies).
  - Update SQL syntax in `app.py` parameters (`?` -> `%s`) and schema creation statements.
