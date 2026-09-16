"""Career roadmap + salary benchmarks.

Both close competitor gaps in ways that could easily turn dishonest -- a
roadmap that credits skills the resume never shows, a salary page that prints
a median of three postings or lets one employer set a whole market. So these
tests pin the guards:

  * roadmap strengths must quote the resume; invented ones are dropped
  * weeks / hours are clamped; no resume -> refused
  * salary medians count each company's range once, never mix currencies,
    and refuse to summarise below the minimum sample

    python scratch/test_career_tools.py            # mocked AI, fake salary rows
    python scratch/test_career_tools.py --live     # also a real roadmap call
"""
import json
import os
import sys
import time
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app                      # noqa: E402
from backend.database import get_db                  # noqa: E402
from backend.routes import generate as gen_mod       # noqa: E402
from backend.services import ats                     # noqa: E402

PASSED, FAILED = 0, 0


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} -- {detail}")


app = create_app()
app.config["TESTING"] = True
with app.app_context():
    with get_db() as db:
        row = db.execute("SELECT user_id, COUNT(*) AS n FROM analyses GROUP BY user_id "
                         "ORDER BY n DESC LIMIT 1").fetchone()
        uid = row["user_id"] if row else None
        try:
            db.execute("DELETE FROM rate_limits WHERE key LIKE ?", (f"%:{uid}",))
        except Exception:
            pass

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid
stranger = app.test_client()
with stranger.session_transaction() as s:
    s["user_id"] = 987654321

with app.test_request_context():
    from flask import session as _s
    _s["user_id"] = uid
    RESUME = gen_mod._resume_text_for()
words = RESUME.split()
REAL_PHRASE = " ".join(words[2:6]) if len(words) > 8 else RESUME

print("CAREER TOOLS -- TEST SUITE")
check("a user with an analyzed resume exists", bool(uid and RESUME), uid)

# ── Roadmap ─────────────────────────────────────────────────────────────────
print("\n[1] Roadmap")
FAKE = json.dumps({
    "summary": "Strong on backend basics; missing data tooling.",
    "strengths": [{"skill": "Grounded skill", "evidence": REAL_PHRASE},
                  {"skill": "Invented skill", "evidence": "led a team of 40 at Google"}],
    "phases": [
        {"title": "SQL foundations", "weeks": 3, "skills": ["SQL"], "learn": ["joins", "window functions"],
         "project": {"name": "Sales dashboard", "build": "Load a public dataset and chart it.",
                     "proves": ["SQL"], "resume_line": "Built a dashboard used by [N] people"},
         "done_when": "Can write a window function unaided."},
        {"title": "", "weeks": 2},
        {"title": "Python for analysis", "weeks": 99, "skills": ["pandas"], "learn": ["groupby"],
         "project": {"name": "Cohort analysis", "build": "Analyse churn.", "proves": ["pandas"],
                     "resume_line": "Cut churn analysis time by [X%]"}, "done_when": "Notebook published."},
    ],
    "interview_topics": ["SQL window functions"],
})
r = client.post("/api/career/roadmap", json={})
check("no target role -> 400", r.status_code == 400, r.status_code)
r = client.post("/api/career/roadmap", json={"target_role": "Data Analyst", "weeks": "lots"})
check("non-numeric weeks -> 400", r.status_code == 400, r.status_code)

seen = {}


def fake_call(prompt, **kw):
    seen["prompt"] = prompt
    return FAKE


with mock.patch.object(gen_mod, "call_groq", side_effect=fake_call):
    r = client.post("/api/career/roadmap", json={"target_role": "Data Analyst", "weeks": 400, "hours_per_week": 0})
    d = r.get_json() or {}
check("returns 200", r.status_code == 200, (r.status_code, d))
check("weeks clamped to 26 and hours to at least 2", d.get("weeks") == 26 and d.get("hours_per_week") == 2,
      (d.get("weeks"), d.get("hours_per_week")))
check("the clamped numbers reach the prompt", "26 weeks at about 2 hours" in seen.get("prompt", ""))
check("a strength quoting the resume is kept",
      [x["skill"] for x in d.get("strengths", [])] == ["Grounded skill"], d.get("strengths"))
check("an invented strength is dropped and counted", d.get("unverified_strengths_removed") == 1)
check("untitled phases are skipped", len(d.get("phases") or []) == 2, len(d.get("phases") or []))
check("phase weeks are clamped", d["phases"][1]["weeks"] == 26, d["phases"][1]["weeks"])
check("projects keep placeholder results",
      "[N]" in d["phases"][0]["project"]["resume_line"], d["phases"][0]["project"])
check("planned_weeks reported", d.get("planned_weeks") == 29, d.get("planned_weeks"))

with mock.patch.object(gen_mod, "call_groq", return_value=FAKE):
    r = stranger.post("/api/career/roadmap", json={"target_role": "Data Analyst"})
check("no analyzed resume -> refused", r.status_code == 400 and (r.get_json() or {}).get("no_resume"), r.status_code)
with mock.patch.object(gen_mod, "call_groq", return_value=json.dumps({"phases": []})):
    r = client.post("/api/career/roadmap", json={"target_role": "Data Analyst"})
check("no phases -> 502", r.status_code == 502, r.status_code)
with mock.patch.object(gen_mod, "call_groq", side_effect=gen_mod.GroqError("down")):
    r = client.post("/api/career/roadmap", json={"target_role": "Data Analyst"})
check("provider down -> 502", r.status_code == 502, r.status_code)

# ── Salary benchmark maths, on controlled rows ──────────────────────────────
print("\n[2] Salary benchmark")
check("percentile interpolates", ats._percentile([10, 20, 30, 40], 0.5) == 25)
check("percentile of one value", ats._percentile([7], 0.25) == 7)


def rows_db(rows):
    class Cur:
        def fetchall(self):
            return rows

    class DB:
        def execute(self, sql, params):
            DB.sql, DB.params = sql, params
            return Cur()

    @contextmanager
    def fake_get_db():
        yield DB()
    return fake_get_db, DB


def row(company, lo, hi, cur="USD", title="Software Engineer", level="senior"):
    return {"title": title, "company": company, "location": "", "country_code": "us",
            "experience_level": level, "salary_min": lo, "salary_max": hi,
            "salary_currency": cur, "apply_url": "https://example.com", "posted_at": None}


rows = [row("Skew Co", 280000, 330000, title=f"Enterprise AE {i}") for i in range(6)]
rows += [row("A", 100000, 120000), row("B", 110000, 130000), row("C", 120000, 140000),
         row("D", 90000, 110000, level="entry"), row("E", 130000, 150000), row("F", 50000, 70000, cur="GBP")]
fake, DB = rows_db(rows)
with mock.patch("backend.database.get_db", fake):
    b = ats.salary_benchmark("software engineer", "US")
check("title words become escaped LIKE clauses", DB.sql.count("LOWER(title) LIKE ? ESCAPE") == 2, DB.sql)
check("country filter applied lower-cased", "us" in DB.params, DB.params)
check("one employer's six identical ranges count once", b["sample"] == 6, b["sample"])
check("median is not dragged up by the repeated employer", b["median"] == 125000, b["median"])
check("currencies are never mixed; the other is reported separately",
      b["currency"] == "USD" and b["currencies"] == {"USD": 6, "GBP": 1}, b["currencies"])
check("company count reported", b["companies"] == 6, b["companies"])

fake, _ = rows_db([row("A", 100000, 120000), row("B", 110000, 130000), row("C", 120000, 140000)])
with mock.patch("backend.database.get_db", fake):
    b = ats.salary_benchmark("software engineer")
check("below the minimum sample -> no median, postings still listed",
      b["enough"] is False and b["median"] is None and len(b["postings"]) == 3, b)

check("empty query refused", "error" in ats.salary_benchmark("  "))
wild = rows_db([])
with mock.patch("backend.database.get_db", wild[0]):
    ats.salary_benchmark("100%_raise")
check("LIKE wildcards in the query are escaped", "%100\\%\\_raise%" in wild[1].params, wild[1].params)

r = client.get("/api/jobs/salaries")
check("route: no query -> 400", r.status_code == 400, r.status_code)
r = client.get("/api/jobs/salaries?q=engineer")
check("route: real lookup on the local corpus -> 200", r.status_code == 200 and "sample" in (r.get_json() or {}), r.status_code)

# ── UI wiring ───────────────────────────────────────────────────────────────
print("\n[3] UI wiring")
ws = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "workspace.html"),
          encoding="utf-8").read()
check("both pages exist", 'id="section-career-roadmap"' in ws and 'id="section-salaries"' in ws)
check("both are in the sidebar", 'data-section="career-roadmap"' in ws and 'data-section="salaries"' in ws)
check("handlers bound in JS, not inline", "addEventListener('click', generateRoadmap)" in ws
      and "addEventListener('click', lookupSalaries)" in ws)
check("salary page states its source and its limits",
      "not what people are actually paid" in ws and "too few to summarise honestly" in ws)
check("posting links are restricted to http(s)", "/^https?:\\/\\//i.test(p.apply_url" in ws)

if "--live" in sys.argv:
    print("\n[4] Live roadmap")
    t0 = time.time()
    r = client.post("/api/career/roadmap", json={"target_role": "Data Analyst", "weeks": 8, "hours_per_week": 6})
    d = r.get_json() or {}
    check("real roadmap returns 200", r.status_code == 200, f"{r.status_code} {time.time() - t0:.1f}s {d.get('error')}")
    check("every kept strength really quotes the resume",
          all(gen_mod._quote_in_answer(x["evidence"], RESUME) for x in d.get("strengths") or []))
    print("      %.1fs, %d phases, planned %s of %s weeks, strengths kept %d, dropped %s" % (
        time.time() - t0, len(d.get("phases") or []), d.get("planned_weeks"), d.get("weeks"),
        len(d.get("strengths") or []), d.get("unverified_strengths_removed")))
    for p in (d.get("phases") or [])[:3]:
        print("      -", p["title"].encode("ascii", "replace").decode(), "|", p["project"]["name"].encode("ascii", "replace").decode())

print("\n" + "=" * 50)
print(f"  RESULT: {PASSED} passed, {FAILED} failed")
print("=" * 50)
sys.exit(1 if FAILED else 0)
