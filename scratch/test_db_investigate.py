import os
import sys
import json

sys.path.insert(0, '.')

from app import app
from backend.database import get_db

print("=== 1. DATABASE CONNECTION AUDIT ===")
pg_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
print("SUPABASE_DB_URL env present:", bool(os.environ.get("SUPABASE_DB_URL")))
print("DATABASE_URL env present:", bool(os.environ.get("DATABASE_URL")))
print("VERCEL env present:", bool(os.environ.get("VERCEL")))

try:
    with app.app_context():
        db = get_db()
        print("Connected DB type:", type(db).__name__)
        
        # Check users count and rows
        try:
            user_rows = db.execute("SELECT id, email, name, created_at FROM users").fetchall()
            print(f"\n--- USERS ({len(user_rows)} rows) ---")
            for u in user_rows:
                print(dict(u))
        except Exception as e:
            print("Error reading users table:", e)

        # Check analyses count and rows
        try:
            analysis_rows = db.execute("SELECT id, user_id, filename, overall_score, created_at FROM analyses").fetchall()
            print(f"\n--- ANALYSES ({len(analysis_rows)} rows) ---")
            for a in analysis_rows:
                print(dict(a))
        except Exception as e:
            print("Error reading analyses table:", e)

        # Check resumes count and rows
        try:
            resume_rows = db.execute("SELECT id, user_id, title, filename, overall_score, created_at, updated_at FROM resumes").fetchall()
            print(f"\n--- RESUMES ({len(resume_rows)} rows) ---")
            for r in resume_rows:
                print(dict(r))
        except Exception as e:
            print("Error reading resumes table:", e)

except Exception as global_err:
    print("GLOBAL DB ERROR:", global_err)
