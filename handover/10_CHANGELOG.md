# Change History & Log

This changelog records the modifications performed during this specific debugging session.

---

## Commit: `d1176d6` (Latest Commit)
- **Hash**: `d1176d6b8ccb7d08b394f7831f24d9c73aef5421`
- **Files Modified**: 
  - `requirements.txt`
  - `app.py`
- **Summary**:
  - Added the missing `python-dotenv` package back to `requirements.txt` to fix import-time crashes.
  - Refactored `google_login()` to utilize `urlencode` from `urllib.parse` instead of deprecated `requests.compat.urlencode`.

---

## Commit: `a899b2d`
- **Hash**: `a899b2da723d85b91ce14293ca81111616c5b854`
- **Files Modified**:
  - `app.py`
  - `requirements.txt`
- **Summary**:
  - Moved the database schema table definitions and migrations from the deprecated `init_db()` into a dedicated `_create_tables_and_migrations(db)` helper.
  - Configured `get_db()` to lazily initialize tables on the first connection call instead of module loading.
  - Removed `else: init_db()` module-level import logic to prevent Vercel container crashes.
  - Removed `libsql-client` from `requirements.txt` to eliminate native C compile issues.

---

## File: `vercel.json` (Local Modification Check)
- **Files Modified**: `vercel.json`
- **Summary**:
  - Reverted from string format (`"templates/**,static/**"`) to proper JSON array syntax (`["templates/**", "static/**"]`) in commit `74278c4` / `a6491ba`.
