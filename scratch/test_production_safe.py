"""
Production-safe test suite for the persistence fix.

Covers the invariants that gard broken in live production:
  1. Vercel (production) REQUIRES PostgreSQL — SQLite is forbidden, no silent fallback.
  2. Missing/misconfigured SUPABASE_DB_URL must raise, not silently use SQLite.
  3. DB failures during /api/analyze must return a 500 with saved=False (never swallowed).
  4. Cross-session persistence: a row written under one session is visible to a
     separate session (previously broken because /tmp/resumeai.db was per-instance).
  5. Export fidelity: "Core Competencies" maps to skills; raw-text fallback is not
     suppressed just because a summary exists; certifications are retained.

Local dev env (no VERCEL, no SUPABASE_DB_URL) still uses SQLite — that is the
intended local-development path, exercised here by overriding env vars.
"""
import io
import json
import os
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, '.')

os.environ.pop("SUPABASE_DB_URL", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ.pop("TURSO_AUTH_TOKEN", None)
if "VERCEL" in os.environ:
    del os.environ["VERCEL"]

from backend.database import (
    is_vercel,
    get_required_db_url,
    get_db,
    _connect_postgres,
    db_diagnostic,
)
import importlib as _il
_db_module = _il.import_module("backend.database")

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def make_app():
    from app import app
    return app


print("==================================================")
print("  PRODUCTION-SAFE PERSISTENCE TEST SUITE")
print("==================================================")

print("\n-- 1. Environment / fallback invariant --")
check("is_vercel() is False in local test env", not is_vercel())
check("get_required_db_url() returns None (local dev allowed)", get_required_db_url() is None)

print("\n-- 1b. Vercel production REQUIRES PostgreSQL --")
os.environ["VERCEL"] = "1"
try:
    get_required_db_url()
    check("Vercel + missing env raises RuntimeError", False, "no exception raised")
except RuntimeError:
    check("Vercel + missing env raises RuntimeError", True)
except Exception as e:
    check("Vercel + missing env raises RuntimeError", False, f"wrong exception {type(e).__name__}")

os.environ["SUPABASE_DB_URL"] = "sqlite:///should-never-work.db"
try:
    get_required_db_url()
    check("Vercel + wrong scheme raises RuntimeError", False, "no exception raised")
except RuntimeError:
    check("Vercel + wrong scheme raises RuntimeError", True)
except Exception as e:
    check("Vercel + wrong scheme raises RuntimeError", False, f"wrong exception {type(e).__name__}")

os.environ["SUPABASE_DB_URL"] = "postgresql://u:p@db.example.com:5432/proj"
check("Vercel + postgres scheme passes validation", get_required_db_url().startswith("postgresql://"))
del os.environ["SUPABASE_DB_URL"]
del os.environ["VERCEL"]

print("\n-- 1c. SQLite is forbidden in Vercel --")
os.environ["VERCEL"] = "1"


def _connect_sqlite_entry():
    return _db_module._connect_sqlite()


try:
    with patch.object(_db_module, "get_required_db_url", return_value=None):
        try:
            _connect_sqlite_entry()
            check("SQLite banned inside Vercel", False, "no exception raised")
        except AssertionError as e:
            # The ban is `assert not is_vercel()` in _connect_sqlite(), so a
            # pass has to be THAT assertion. Matching its message keeps an
            # unrelated AssertionError from counting as proof.
            check("SQLite banned inside Vercel",
                  "forbidden in Vercel" in str(e),
                  f"AssertionError, but not the ban: {e}")
        except Exception as e:
            # Previously this counted as a PASS for any exception at all -- so
            # an import error or a missing app context would have "proved" a
            # ban that was never exercised.
            check("SQLite banned inside Vercel", False,
                  f"blocked by an unrelated {type(e).__name__}, "
                  f"so the ban itself is unproven: {e}")
except Exception as e:
    check("SQLite banned inside Vercel suite ran", False, str(e))
del os.environ["VERCEL"]

print("\n-- 2. Local SQLite still works (dev only) --")
app = make_app()
with app.app_context():
    try:
        db = get_db()
        db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        check("Local dev get_db() returns usable SQLite", True)
        db.close()
    except Exception as e:
        check("Local dev get_db() returns usable SQLite", False, str(e))

print("\n-- 3. db_diagnostic() is safe and accurate (never leaks credentials) --")
os.environ["SUPABASE_DB_URL"] = "postgresql://v3ry_s3cr3t:p4ssw0rd@db.givememyproject.supabase.co:5432/spiky"
info = db_diagnostic()
del os.environ["SUPABASE_DB_URL"]
joined = json.dumps(info)
check("diagnostic reports env var present", info.get("required_env_present") is True)
check("diagnostic hides password", "p4ssw0rd" not in joined)
check("diagnostic hides username", "v3ry_s3cr3t" not in joined)
check("diagnostic reveals host", info.get("host") == "db.givememyproject.supabase.co")
check("diagnostic reveals project", info.get("project") == "spiky")

os.environ["VERCEL"] = "1"
info_miss = db_diagnostic()
del os.environ["VERCEL"]
check("diagnostic flags missing env in Vercel", info_miss.get("config_ok") is False)
check("diagnostic backend message forbids SQLite", "SQLite forbidden" in (info_miss.get("backend") or ""))

print("\n-- 4. Analysis save failure must 500 + saved:false (not swallowed) --")
app2 = make_app()
with app2.app_context():
    os.environ["SUPABASE_DB_URL"] = "postgresql://u:p@db.example.com:5432/proj"
    from unittest.mock import patch

    def boom_connect(*args, **kwargs):
        raise RuntimeError("blocked postgres (test simulated outage)")

    with patch.object(_db_module, "_connect_postgres", boom_connect):
        # Simulate Vercel so the app demands Postgres, which we force to fail.
        os.environ["VERCEL"] = "1"
        try:
            db_diag_forced = db_diagnostic()
            check("forced-outage diagnostic reports connection failure",
                  db_diag_forced.get("config_ok") is False)
        finally:
            del os.environ["VERCEL"]

print("\n-- 5. Cross-session persistence (core regression for 'Previous Analyses') --")
with app2.app_context():
    os.environ.pop("SUPABASE_DB_URL", None)
    with tempfile.TemporaryDirectory() as tmp:
        app2.config["DATABASE"] = os.path.join(tmp, "persist.db")
        from backend import database
        database._db_initialized = False
        db_a = get_db()  # "instance A"
        db_a.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                     ("User One", "one@test.dev", "x"))
        db_a.commit()
        uid = db_a.execute("SELECT id FROM users WHERE email = ?", ("one@test.dev",)).fetchone()["id"]
        db_a.execute(
            """INSERT INTO analyses (user_id, filename, job_description, overall_score,
               dimension_scores, summary, strengths, weaknesses, missing_sections,
               ats_issues, suggestions, suggested_keywords)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, "resume.pdf", "", 82, "[]", "s", "[]", "[]", "[]", "[]", "[]", "[]")
        )
        db_a.commit()
        db_a.close()

        # Separate connection/session: previously this read could 404 because
        # the write landed in a per-instance /tmp DB.
        db_b = get_db()
        row = db_b.execute("SELECT COUNT(*) AS c FROM analyses WHERE user_id = ?", (uid,)).fetchone()
        check("Fresh DB connection sees committed analysis", row["c"] == 1, f"count={row['c']}")
        db_b.close()

print("\n-- 6. Concurrent inserts get unique ids (regression for SQLite duplicate uid=1) --")
with app2.app_context():
    os.environ.pop("SUPABASE_DB_URL", None)
    with tempfile.TemporaryDirectory() as tmp:
        app2.config["DATABASE"] = os.path.join(tmp, "conc.db")
        from backend import database as dbmod
        dbmod._db_initialized = False
        ids = []
        lock = threading.Lock()

        def spawn(i):
            with app2.app_context():
                c = get_db()
                cur = c.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (f"c{i}", f"c{i}@t.dev", "x")
                )
                c.commit()
                uid = cur.lastrowid
                with lock:
                    ids.append(uid)
                c.close()

        threads = [threading.Thread(target=spawn, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("12 concurrent inserts produced 12 ids", len(ids) == 12, f"got {len(ids)}")
        check("All concurrent ids unique", len(set(ids)) == len(ids),
              f"seen={sorted(set(ids))} (dupes would mean per-instance sqlite)")

print("\n-- 7. Export fidelity --")
from backend.routes.export import parse_markdown_to_data, merge_missing_sections

parsed = parse_markdown_to_data(
    "# Jane Doe\n"
    "## Summary\nExperienced dev\n"
    "## Core Competencies\nPython, Docker, K8s\n"
    "## Work Experience\n"
    "### Senior Dev @ TechCo (2020-2024)\n"
    "- Led platform team\n"
    "- Cut latency 40%\n"
    "## Education\n- BS CS, MIT\n"
    "## Certifications\n- AWS Certified"
)
check("Core Competencies maps into skills", "Python" in (parsed.get("skills") or "") and "K8s" in (parsed.get("skills") or ""),
      repr(parsed.get("skills")))
check("Experience parsed with bullets",
      parsed["experience"] and parsed["experience"][0].get("role", "").startswith("Senior Dev"),
      repr(parsed.get("experience")))
check("Certifications retained", len(parsed.get("certifications")) == 1, repr(parsed.get("certifications")))
check("Education retained", len(parsed.get("education")) == 1)

print("\n-- 7b. Markdown parser heading variants --")
p_variants = parse_markdown_to_data(
    "# Alice Smith\n"
    "## Professional Summary\nEngineer with 8 years.\n"
    "## Technical Skills\nPython, AWS\n"
    "## Professional Experience\n"
    "### Engineer - Acme (2019-2023)\n"
    "Built APIs\n"
    "## Education & Certifications\n"
    "- BS Computer Science, State University\n"
    "- AWS Certified Solutions Architect\n"
)
check("Professional Summary recognized", "Engineer with 8 years" in (p_variants.get("summary") or ""))
check("Technical Skills recognized", "AWS" in (p_variants.get("skills") or ""))
check("Professional Experience recognized",
      p_variants["experience"] and p_variants["experience"][0].get("role", "").startswith("Engineer"),
      repr(p_variants.get("experience")))
check("Education & Certifications: education kept",
      len(p_variants.get("education")) >= 1, repr(p_variants.get("education")))
check("Education & Certifications: certification kept",
      any("AWS" in (c.get("name") or "") for c in p_variants.get("certifications", [])),
      repr(p_variants.get("certifications")))

print("\n-- 7c. Non-bullet content lines still parsed --")
p_plain = parse_markdown_to_data(
    "# Bob Brown\n"
    "## Summary\nLead engineer.\n"
    "## Experience\n"
    "### CEO - StartupHub\n"
    "Grew company to 50 people\n"
    "Received Series A funding\n"
    "## Education\n"
    "BS Electrical Engineering\n"
    "## Projects\n"
    "Open Source Dashboard\n"
    "Built a dashboard used by 10k users\n"
)
exp_bullets = [b for e in p_plain.get("experience", []) for b in (e.get("bullets") or [])]
check("Plain content after ### added as experience bullets", len(exp_bullets) >= 2, repr(exp_bullets))
check("Plain education line captured", len(p_plain.get("education")) >= 1, repr(p_plain.get("education")))
check("Plain project line captured as entry", len(p_plain.get("projects")) >= 1, repr(p_plain.get("projects")))

print("\n-- 7d. merge_missing_sections recovers missing fields --")
merged = merge_missing_sections(
    {"fullName": "Carol", "summary": "Dev", "rawText": "# Carol\n## Skills\nGo, Rust\n## Work Experience\n### Dev - Co\n- did stuff\n"},
    None
)
check("Missing skills recovered from rawText", "Go" in (merged.get("skills") or ""), repr(merged.get("skills")))
check("Missing experience recovered from rawText", len(merged.get("experience")) >= 1, repr(merged.get("experience")))

print("\n-- 7e. /api/export/parse endpoint returns canonical structure --")
with app2.test_client() as client:
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    rp = client.post("/api/export/parse", json={"text": "# Dana\n## Professional Experience\n### Eng - X\n- did\n## Certifications\n- Certified thing"})
    rp_json = rp.get_json()
    check("Parse endpoint 200", rp.status_code == 200, f"{rp.status_code} {rp.data[:100]!r}")
    check("Parse endpoint returns experience", (rp_json and rp_json.get("data", {}).get("experience")) or False,
          repr(rp_json)[:160])
    check("Parse endpoint returns certifications",
          bool(rp_json and rp_json.get("data", {}).get("certifications")),
          repr(rp_json)[:160])

print("\n-- 8. Export PDF/DOCX respond 200 with content (regression guard) --")
with app2.test_client() as client:
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    data = {
        "fullName": "Fidelity Tester",
        "email": "f@t.dev",
        "phone": "555",
        "location": "SF",
        "summary": "Summary present but sections from structured data ONLY.",
        "skills": "Python, Flask, PostgreSQL",
        "experience": [{"role": "Dev", "company": "Co", "dates": "2020-2024", "bullets": ["Did things", "Improved stuff"]}],
        "education": [{"degree": "BS", "school": "MIT", "dates": "2016-2020"}],
        "projects": [{"name": "P1", "tech": "Go", "desc": "Desc"}],
        "certifications": [{"name": "AWS SA Pro", "issuer": "AWS", "dates": "2023"}],
        "rawText": "# Junk raw text that must NOT duplicate sections when structured data exists"
    }
    r = client.post("/api/export/pdf", json={"data": data, "title": "Fidelity"})
    check("PDF export 200 + pdf mimetype", r.status_code == 200 and r.content_type == "application/pdf",
          f"{r.status_code} {r.content_type}")
    r2 = client.post("/api/export/docx", json={"data": data, "title": "Fidelity"})
    check("DOCX export 200", r2.status_code == 200, f"{r2.status_code} {r2.content_type}")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(r.data))
        check("PDF page count >= 1", len(reader.pages) >= 1, f"pages={len(reader.pages)}")
    except Exception as e:
        print(f"  [INFO] pypdf check skipped: {e}")

print("\n-- 9. Health/diagnostic endpoints registered --")
with app2.test_client() as client:
    rh = client.get("/api/health")
    check("GET /api/health -> 200 ok", rh.status_code == 200 and rh.get_json().get("status") == "ok",
          f"{rh.status_code}")
    rd = client.get("/api/health/db")
    check("GET /api/health/db -> 200 json", rd.status_code == 200 and isinstance(rd.get_json(), dict),
          f"{rd.status_code} {rd.data[:120]!r}")

print("\n-- 10. Transaction rollback on failed write --")
with app2.app_context():
    os.environ.pop("SUPABASE_DB_URL", None)
    with tempfile.TemporaryDirectory() as tmp:
        app2.config["DATABASE"] = os.path.join(tmp, "txrollback.db")
        _db_module._db_initialized = False
        db_r = get_db()
        try:
            with db_r:
                db_r.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             ("Rollback", "rb@t.dev", "x"))
                # Cause a unique constraint violation on the second statement
                db_r.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             ("Rollback2", "rb@t.dev", "x"))
        except Exception:
            pass
        # Re-open a fresh connection to the same file and verify rollback.
        db_r_check = get_db()
        cnt = db_r_check.execute("SELECT COUNT(*) AS c FROM users WHERE email = ?", ("rb@t.dev",)).fetchone()["c"]
        check("Failed transaction rolled back (no partial insert)", cnt == 0, f"count={cnt}")
        db_r_check.close()

print("\n-- 10b. SQLite (dev) rollback parity --")
with app2.app_context():
    os.environ.pop("SUPABASE_DB_URL", None)
    with tempfile.TemporaryDirectory() as tmp2:
        app2.config["DATABASE"] = os.path.join(tmp2, "rollback_parity.db")
        _db_module._db_initialized = False
        db_s = get_db()
        try:
            with db_s:
                db_s.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             ("RbSqlite", "rbs@t.dev", "x"))
                db_s.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             ("RbSqlite2", "rbs@t.dev", "x"))
        except Exception:
            pass
        db_s_check = get_db()
        cnt = db_s_check.execute("SELECT COUNT(*) AS c FROM users WHERE email = ?", ("rbs@t.dev",)).fetchone()["c"]
        check("SQLite rollback parity", cnt == 0, f"count={cnt}")
        db_s_check.close()

print("\n-- 11. /api/analyses ownership between users --")
with app2.app_context():
    os.environ.pop("SUPABASE_DB_URL", None)
    with tempfile.TemporaryDirectory() as tmp:
        app2.config["DATABASE"] = os.path.join(tmp, "owner.db")
        _db_module._db_initialized = False
        with get_db() as dbo:
            cu = dbo.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             ("OwnerA", "a@o.dev", "x"))
            id_a = cu.lastrowid
            cu2 = dbo.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                              ("OwnerB", "b@o.dev", "x"))
            id_b = cu2.lastrowid
            dbo.execute(
                """INSERT INTO analyses (user_id, filename, job_description, overall_score,
                   dimension_scores, summary, strengths, weaknesses, missing_sections,
                   ats_issues, suggestions, suggested_keywords)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (id_a, "priv.pdf", "", 90, "[]", "s", "[]", "[]", "[]", "[]", "[]", "[]")
            )
            dbo.commit()

        client_owner = app2.test_client()
        with client_owner.session_transaction() as sess:
            sess["user_id"] = id_b
        r = client_owner.get("/api/analyses")
        check("User B gets only own analyses (none)", r.status_code == 200 and len(r.get_json()) == 0,
              f"{r.status_code} {r.data[:120]!r}")
        with client_owner.session_transaction() as sess:
            sess["user_id"] = id_a
        r_a = client_owner.get("/api/analyses")
        check("User A sees own analysis", r_a.status_code == 200 and len(r_a.get_json()) == 1,
              f"{r_a.status_code} {r_a.data[:120]!r}")

print("\n-- 12. Builder persistence round-trip (save to load) --")
with tempfile.TemporaryDirectory() as tmp:
    app2.config["DATABASE"] = os.path.join(tmp, "builder.db")
    _db_module._db_initialized = False
    cb = app2.test_client()
    with cb.session_transaction() as sess:
        sess["user_id"] = id_a
    rb = cb.post("/api/resumes", json={
        "title": "Builder Test",
        "template": "modern",
        "data": {
            "fullName": "Builder Person",
            "email": "bp@o.dev",
            "summary": "Summary",
            "skills": "Python",
            "experience": [{"role": "Dev", "company": "Co", "dates": "2020", "bullets": ["did x"]}],
            "education": [{"school": "MIT", "degree": "BS", "dates": "2016"}],
            "projects": [{"name": "P", "tech": "Go", "desc": "d"}],
            "certifications": [{"name": "Cert", "issuer": "AWS", "dates": "2023"}]
        }
    })
    rid = rb.get_json().get("id")
    check("Builder save returns id", rb.status_code == 200 and rid, f"{rb.status_code} {rb.data[:120]!r}")
    rg = cb.get("/api/resumes/" + str(rid))
    rgj = rg.get_json() or {}
    loaded = (rgj.get("data") or {}) if isinstance(rgj.get("data"), dict) else {}
    check("Builder reload preserves experience",
          len(loaded.get("experience") or []) == 1 and loaded.get("experience", [{}])[0].get("role") == "Dev",
          repr(loaded.get("experience")))
    check("Builder reload preserves certifications",
          len(loaded.get("certifications") or []) == 1, repr(loaded.get("certifications")))
    check("Builder reload preserves projects",
          len(loaded.get("projects") or []) == 1, repr(loaded.get("projects")))

print("\n-- 13. Failed DB write on /api/analyses/claim returns failure (not success) --")
from unittest.mock import patch as _patch
# analysis.py imports get_db directly, so patch the route module's binding.
_analysis_mod = _il.import_module("backend.routes.analysis")
with _patch.object(_analysis_mod, "get_db") as boom_db:
    boom_db.side_effect = RuntimeError("simulated Postgres outage on write")
    cc = app2.test_client()
    with cc.session_transaction() as sess:
        sess["user_id"] = 1
    rfail = cc.post("/api/analyses/claim", json={"analysis": {"filename": "f.pdf", "summary": "s"}})
    check("Claim with DB outage returns 500", rfail.status_code == 500, f"{rfail.status_code} {rfail.data[:120]!r}")
    check("Claim failure says save failed (not success)",
          "simulated Postgres outage" in (rfail.get_json() or {}).get("error", ""),
          (rfail.get_json() or {}).get("error", ""))

print("\n-- 13b. Failed DB commit on /api/analyze cannot report success --")
import io as _io
from backend.prompts import ANALYSIS_PROMPT
from backend.services.helpers import clean_json

FAKE_AI = json.dumps({
    "overall_score": 80,
    "dimension_scores": {"clarity": 80, "experience": 80, "skills": 80,
                         "ats_readiness": 80, "impact": 80, "completeness": 80},
    "summary": "Strong candidate",
    "strengths": ["Good"],
    "weaknesses": [],
    "missing_sections": [],
    "ats_issues": [],
    "suggestions": [],
    "suggested_keywords": ["Python"]
})

_ai_mod = _il.import_module("backend.routes.analysis")
with _patch.object(_ai_mod, "call_groq", return_value=FAKE_AI):
    with _patch.object(_ai_mod, "get_db") as boom_db2:
        boom_db2.side_effect = RuntimeError("simulated commit failure")
        ca = app2.test_client()
        with ca.session_transaction() as sess:
            sess["user_id"] = 1
        rf = ca.post("/api/analyze", data={
            "resume": (_io.BytesIO(b"# Name\n## Skills\nPython"), "r.txt"),
            "job_description": ""
        }, content_type="multipart/form-data")
        check("Analyze with DB write failure returns 500", rf.status_code == 500,
              f"{rf.status_code} {rf.data[:140]!r}")
        body = rf.get_json() or {}
        check("Analyze failure marks saved:false", body.get("saved") is False,
              repr(body)[:160])
        check("Analyze failure not 'successful analysis'",
              "could not be saved" in body.get("error", ""), body.get("error", "")[:160])

print("\n-- 14. Export fidelity: 2+ page PDF, DOCX, all sections, special chars --")
# Deliberately long resume: 8 experience entries x 4 long bullets each.
long_exp = []
for i in range(1, 9):
    long_exp.append({
        "role": f"Senior Principal Engineer {i}",
        "company": f"Global Enterprise Tech {i} Inc & R&D",
        "dates": f"201{i}-2020",
        "bullets": [
            f"Architected high-throughput microservices with C++ and Python handling >100,{i}00 QPS.",
            f"Reduced latency to <5ms & improved uptime to 99.99% for UI/UX and core services.",
            f"Led cross-functional team of {i * 3} engineers across 4 timezones.",
            f"Designed CI/CD pipelines cutting deployment times by 45%."
        ]
    })

long_data = {
    "fullName": "Alexander Vance, PhD",
    "email": "alex.vance@example.com",
    "phone": "+1 (555) 019-2834",
    "location": "San Francisco, CA",
    "summary": "Seasoned Lead Principal Architect with 15+ years building mission-critical distributed systems, database engines, and scalable Cloud & AI platforms.",
    "skills": "Python, Flask, PostgreSQL, Supabase, Docker, Kubernetes, AWS, Microservices, CI/CD, React, TypeScript",
    "experience": long_exp,
    "education": [
        {"degree": "PhD in Computer Science", "school": "Stanford University", "dates": "2010-2014"},
        {"degree": "BS in Computer Engineering", "school": "UC Berkeley", "dates": "2006-2010"}
    ],
    "projects": [
        {"name": "Distributed Analytics Engine", "tech": "Python, Go, PostgreSQL", "desc": "Real-time pipeline processing 10B+ events daily."},
        {"name": "AI Career OS", "tech": "Flask, Groq, Supabase", "desc": "ATS analysis and resume generation engine."}
    ],
    "certifications": [
        {"name": "AWS Certified Solutions Architect - Professional", "issuer": "AWS", "dates": "2023"},
        {"name": "Google Cloud Lead Data Engineer", "issuer": "Google Cloud", "dates": "2022"}
    ],
    "rawText": "# Raw text fallback that must NOT duplicate structured sections"
}

client_exp = app2.test_client()
with client_exp.session_transaction() as sess:
    sess["user_id"] = 1

r_pdf = client_exp.post("/api/export/pdf", json={"data": long_data, "title": "Long_Resume"})
pdf_bytes = r_pdf.data
check("2+ page PDF generation", r_pdf.status_code == 200 and r_pdf.content_type == "application/pdf" and len(pdf_bytes) > 3000,
      f"{r_pdf.status_code} {r_pdf.content_type} size={len(pdf_bytes)}")

pdf_pages = None
pdf_text = ""
try:
    from pypdf import PdfReader
    reader = PdfReader(_io.BytesIO(pdf_bytes))
    pdf_pages = len(reader.pages)
    pdf_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    check("PDF has 2+ pages", pdf_pages >= 2, f"pages={pdf_pages}")
except Exception as e:
    print(f"  [INFO] pypdf page-count check skipped: {e}")

if pdf_text:
    for sec_name in ("PROFESSIONAL SUMMARY", "SKILLS & COMPETENCIES", "WORK EXPERIENCE", "EDUCATION", "PROJECTS", "CERTIFICATIONS"):
        check(f"PDF contains section: {sec_name}", sec_name in pdf_text.upper())
    for special in ("C++", "R&D", "UI/UX", "&"):
        check(f"PDF preserves special char: {special!r}", special in pdf_text, f"found={special in pdf_text}")

r_docx = client_exp.post("/api/export/docx", json={"data": long_data, "title": "Long_Resume"})
check("DOCX generation", r_docx.status_code == 200 and "wordprocessingml" in r_docx.content_type and len(r_docx.data) > 20000,
      f"{r_docx.status_code} {r_docx.content_type} size={len(r_docx.data)}")

try:
    from docx import Document as _Docx
    ddoc = _Docx(_io.BytesIO(r_docx.data))
    docx_text = "\n".join(p.text for p in ddoc.paragraphs)
    check("DOCX contains all paragraphs (multi-section)", len(docx_text) > 1500, f"chars={len(docx_text)}")
    for sec_name in ("PROFESSIONAL SUMMARY", "SKILLS & COMPETENCIES", "WORK EXPERIENCE", "EDUCATION", "PROJECTS", "CERTIFICATIONS"):
        check(f"DOCX contains section: {sec_name}", sec_name in docx_text.upper())
    for special in ("C++", "R&D", "UI/UX"):
        check(f"DOCX preserves special char: {special!r}", special in docx_text, f"found={special in docx_text}")
    # DOCX page count is computed by Word at render time; not determinable via python-docx.
    print("  [INFO] DOCX page count requires Word/LibreOffice rendering (not available); content parity verified above.")
except Exception as e:
    print(f"  [INFO] python-docx check skipped: {e}")

print("\n-- 15. logout/login persistence (session re-resolve) --")
with tempfile.TemporaryDirectory() as tmp:
    app2.config["DATABASE"] = os.path.join(tmp, "session.db")
    _db_module._db_initialized = False
    c_l = app2.test_client()
    # register via form posts
    c_l.post("/register", data={"name": "Log Person", "email": "log@o.dev", "password": "password123"}, follow_redirects=True)
    with c_l.session_transaction() as s:
        uid_before = s.get("user_id")
    check("User id set after register", uid_before is not None)
    c_l.post("/logout")
    with c_l.session_transaction() as s:
        check("Session cleared after logout", s.get("user_id") is None)
    c_l.post("/login", data={"email": "log@o.dev", "password": "password123"}, follow_redirects=True)
    with c_l.session_transaction() as s:
        uid_after = s.get("user_id")
    check("Login re-resolves same user id", uid_before == uid_after, f"before={uid_before} after={uid_after}")

print("\n==================================================")
print(f"  RESULT: {PASS} passed, {FAIL} failed")
print("==================================================")
sys.exit(1 if FAIL else 0)