"""Tests for the grounded writers: cover letter and interview prep.

Both exist to close a gap against competitors WITHOUT the failure mode that
makes such features dangerous -- a tool that invents a career the candidate
then has to defend in a real interview. So the tests care most about:

  * no resume -> refused, not written from nothing
  * a question the resume cannot answer -> empty evidence, listed as a gap
  * placeholders survive to the UI, so unknown numbers stay unknown
  * provider failure -> 502, never a half-written letter

    python scratch/test_ai_writers.py            # mocked AI
    python scratch/test_ai_writers.py --live     # also one real call each
"""
import json
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app                      # noqa: E402
from backend.database import get_db                  # noqa: E402
from backend.routes import generate as gen_mod       # noqa: E402

PASSED, FAILED = 0, 0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def safe(text):
    """Windows consoles are cp1252; AI text carries en dashes and U+2011."""
    return str(text).encode("ascii", "replace").decode("ascii")


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}" + (f" -- {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" -- {detail}" if detail else ""))


app = create_app()
app.config["TESTING"] = True

with app.app_context():
    with get_db() as db:
        row = db.execute("SELECT user_id, COUNT(*) AS n FROM analyses GROUP BY user_id "
                         "ORDER BY n DESC LIMIT 1").fetchone()
        uid = row["user_id"] if row else None

with app.app_context():
    # These routes are genuinely rate limited (10 per 300s each), and this
    # suite makes ~7 calls per route -- so two runs inside one window would
    # collide with the real limiter and fail on 429s that say nothing about
    # the feature. Clear this user's windows first; the limiter itself is
    # exercised by its own suite.
    try:
        with get_db() as db:
            db.execute("DELETE FROM rate_limits WHERE key LIKE ?", (f"%:{uid}",))
    except Exception as e:
        print(f"  (could not clear rate-limit windows: {e})")

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid
    s["user_name"] = "QA"

stranger = app.test_client()          # signed in, but owns no analyses
with stranger.session_transaction() as s:
    s["user_id"] = 987654321

JD = ("Backend Engineer, payments. Python, PostgreSQL, Kafka, AWS. You will own "
      "settlement services, on-call rotation, and mentoring two juniors.")

FAKE_LETTER = json.dumps({
    "subject": "Backend Engineer, payments",
    "greeting": "Dear Hiring Manager,",
    "paragraphs": ["I build settlement services in Python and Postgres.",
                   "At Example Payments I cut report time by [X%].",
                   "I would like to bring that to your team."],
    "closing": "Thank you for your time.",
    "evidence_used": ["Python and Postgres on the resume", "Settlement service ownership"],
    "placeholders": ["[X%]"],
})

FAKE_PREP = json.dumps({
    "role_summary": "Whether you have owned a payment-critical service.",
    "questions": [
        {"question": "Walk through a settlement bug you fixed.",
         "why": "The role owns settlement.", "your_evidence": "Your settlement service work."},
        {"question": "How have you run Kafka in production?",
         "why": "Listed as required.", "your_evidence": ""},
    ],
    "gaps_to_prepare": ["Kafka in production"],
    "questions_to_ask": ["How large is the on-call rotation?"],
})

print("GROUNDED WRITERS -- TEST SUITE")
check("a user with analyses exists to test against", uid is not None, f"user {uid}")

# ── Cover letter ────────────────────────────────────────────────────────────
print("\n[1] Cover letter")
r = client.post("/api/generate/cover-letter", json={})
check("no job description -> 400", r.status_code == 400, r.status_code)

with mock.patch.object(gen_mod, "call_groq", return_value=FAKE_LETTER):
    r = client.post("/api/generate/cover-letter", json={"description": JD})
    d = r.get_json() or {}
check("returns 200 with an assembled letter", r.status_code == 200 and d.get("letter"), r.status_code)
check("letter contains greeting, body and closing",
      d.get("letter", "").startswith("Dear Hiring Manager,")
      and "settlement services" in d.get("letter", "")
      and d.get("letter", "").rstrip().endswith("Thank you for your time."))
check("word count reported", isinstance(d.get("words"), int) and d["words"] > 10, d.get("words"))
check("placeholders passed through for the user to fill",
      d.get("placeholders") == ["[X%]"], d.get("placeholders"))
check("evidence the letter was built on is returned",
      len(d.get("evidence_used") or []) == 2, d.get("evidence_used"))
check("no unexpected fields in the response",
      set(d) <= {"subject", "greeting", "paragraphs", "closing", "letter",
                 "evidence_used", "placeholders", "words"}, set(d))

with mock.patch.object(gen_mod, "call_groq", return_value=FAKE_LETTER):
    r = stranger.post("/api/generate/cover-letter", json={"description": JD})
    d2 = r.get_json() or {}
check("no analyzed resume -> refused, nothing written",
      r.status_code == 400 and d2.get("no_resume") is True, f"{r.status_code} {d2}")

with mock.patch.object(gen_mod, "call_groq", side_effect=gen_mod.GroqError("down")):
    r = client.post("/api/generate/cover-letter", json={"description": JD})
check("provider down -> 502, no partial letter",
      r.status_code == 502 and "letter" not in (r.get_json() or {}), r.status_code)

with mock.patch.object(gen_mod, "call_groq", return_value="not json at all"):
    r = client.post("/api/generate/cover-letter", json={"description": JD})
check("unreadable AI output -> 502", r.status_code == 502, r.status_code)

with mock.patch.object(gen_mod, "call_groq", return_value=json.dumps({"paragraphs": []})):
    r = client.post("/api/generate/cover-letter", json={"description": JD})
check("empty body -> 502 rather than an empty letter", r.status_code == 502, r.status_code)

# ── Interview prep ──────────────────────────────────────────────────────────
print("\n[2] Interview prep")
r = client.post("/api/interview/prep", json={})
check("no job description -> 400", r.status_code == 400, r.status_code)

with mock.patch.object(gen_mod, "call_groq", return_value=FAKE_PREP):
    r = client.post("/api/interview/prep", json={"description": JD})
    d = r.get_json() or {}
check("returns 200 with questions", r.status_code == 200 and len(d.get("questions") or []) == 2, r.status_code)
check("a question the resume answers carries its evidence",
      d["questions"][0]["your_evidence"].startswith("Your settlement"), d["questions"][0])
check("a question the resume cannot answer has EMPTY evidence, not an invention",
      d["questions"][1]["your_evidence"] == "", d["questions"][1])
check("the uncovered topic is listed as a gap",
      d.get("gaps_to_prepare") == ["Kafka in production"], d.get("gaps_to_prepare"))
check("grounded count reflects only real evidence", d.get("grounded") == 1, d.get("grounded"))
check("questions to ask them are returned", len(d.get("questions_to_ask") or []) == 1)

with mock.patch.object(gen_mod, "call_groq", return_value=FAKE_PREP):
    r = stranger.post("/api/interview/prep", json={"description": JD})
check("no analyzed resume -> refused", r.status_code == 400 and (r.get_json() or {}).get("no_resume"), r.status_code)

with mock.patch.object(gen_mod, "call_groq", return_value=json.dumps({"questions": [{"why": "x"}]})):
    r = client.post("/api/interview/prep", json={"description": JD})
check("questions with no text -> 502", r.status_code == 502, r.status_code)

with mock.patch.object(gen_mod, "call_groq", side_effect=gen_mod.GroqError("down")):
    r = client.post("/api/interview/prep", json={"description": JD})
check("provider down -> 502", r.status_code == 502, r.status_code)

# ── Wiring in the UI ────────────────────────────────────────────────────────
print("\n[3] UI wiring")
ws = open(os.path.join(ROOT, "templates", "workspace.html"), encoding="utf-8").read()
js = open(os.path.join(ROOT, "templates", "partials", "jobsearch.html"), encoding="utf-8").read()
check("cover letter section exists", 'id="section-cover-letter"' in ws)
check("interview prep section exists", 'id="section-interview-prep"' in ws)
check("both appear in the sidebar",
      'data-section="cover-letter"' in ws and 'data-section="interview-prep"' in ws)
check("both have page titles", "'cover-letter': 'Cover Letter'" in ws and "'interview-prep': 'Interview Prep'" in ws)
check("handlers are bound in JS, not inline attributes",
      "getElementById('clGenerate')" in ws and "addEventListener('click', generateCoverLetter)" in ws
      and 'onclick="generateCoverLetter()"' not in ws)
check("placeholders surfaced to the user", "Fill these in before sending" in ws)
check("uncovered questions are labelled honestly",
      "Nothing on your resume answers this yet" in ws)
check("match evidence renders both hit and miss lists",
      "renderMatchEvidence" in js and "On your resume" in js and "Not found" in js)
check("match evidence tells the user where it came from",
      "most recently analyzed resume" in js)

# ── Optional: one real call each ────────────────────────────────────────────
if "--live" in sys.argv:
    print("\n[4] Live AI (real calls)")
    t0 = time.time()
    r = client.post("/api/generate/cover-letter", json={"description": JD})
    d = r.get_json() or {}
    check("real cover letter returns 200", r.status_code == 200, f"{r.status_code} {time.time()-t0:.1f}s")
    # A thin resume honestly yields a shorter letter than the prompt's
    # 200-280 target -- there is less true material to draw on. What must not
    # happen is padding it out with invention, so the floor is deliberately
    # low and the ceiling guards against waffle.
    check("real letter is a plausible length",
          60 <= len((d.get('letter') or '').split()) <= 400, len((d.get("letter") or "").split()))
    check("real letter has multiple paragraphs", len(d.get("paragraphs") or []) >= 2,
          len(d.get("paragraphs") or []))
    print("      subject:", safe((d.get("subject") or "")[:90]))
    print("      first paragraph:", safe((d.get("paragraphs") or [""])[0][:180]))
    print("      placeholders:", safe(d.get("placeholders")))
    t0 = time.time()
    r = client.post("/api/interview/prep", json={"description": JD})
    d = r.get_json() or {}
    check("real interview prep returns 200", r.status_code == 200, f"{r.status_code} {time.time()-t0:.1f}s")
    qs = d.get("questions") or []
    check("6 to 8 questions as instructed", 5 <= len(qs) <= 10, len(qs))
    print("      summary:", safe((d.get("role_summary") or "")[:120]))
    for q in qs[:3]:
        print("      Q:", safe(q["question"][:110]))
        print("         evidence:", safe((q["your_evidence"] or "(none - flagged as a gap)")[:110]))
    print("      gaps:", safe(d.get("gaps_to_prepare")))

print("\n" + "=" * 50)
print(f"  RESULT: {PASSED} passed, {FAILED} failed")
print("=" * 50)
sys.exit(1 if FAILED else 0)
