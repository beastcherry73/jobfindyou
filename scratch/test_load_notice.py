"""Tests for the "High traffic right now" notice in the analysis flow.

The whole point of this feature is that it must never be theatre, so the
tests are mostly about when the warning must STAY HIDDEN:

  * normal conditions -> hidden
  * genuinely saturated AI pool -> shown, reason ai_capacity
  * genuinely slow recent analyses -> shown, reason slow_recent
  * one model still able to serve -> hidden (not "nearly busy")
  * below the sample floor -> hidden (one cold start is not a trend)
  * the signal source failing -> hidden, endpoint still 200
  * repeated calls -> byte-identical (nothing probabilistic)
  * a real analysis still works and is what feeds the latency signal

    python scratch/test_load_notice.py
"""
import io
import json
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app                       # noqa: E402
from backend.routes import analysis as analysis_mod   # noqa: E402
from backend.services import ai                       # noqa: E402

PASSED, FAILED = 0, 0


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
client = app.test_client()


def eligible_keys():
    """The models pool_status would consider for an analysis, same filters."""
    keys = []
    for spec in ai._MODELS:
        if not spec["json_ok"]:
            continue
        if analysis_mod.ANALYSIS_MAX_TOKENS < spec["min_budget"]:
            continue
        if spec["max_budget"] is not None and analysis_mod.ANALYSIS_MAX_TOKENS > spec["max_budget"]:
            continue
        if not os.environ.get(ai._PROVIDER_CONF[spec["provider"]]["env"], ""):
            continue
        keys.append((ai._key(spec["provider"], spec["model"]), spec["tpm_hint"]))
    return keys


def state_entry(tpm, *, cooling=False, exhausted=False):
    now = time.time()
    return {
        "remaining_tokens": 50 if exhausted else None,
        "limit_tokens": tpm,
        "remaining_requests": None,
        "limit_requests": None,
        "quota_expires_at": now + 60 if exhausted else 0.0,
        "cooldown_until": now + 300 if cooling else 0.0,
        "reserved_tokens": 0,
    }


def load(**kwargs):
    r = client.get("/api/analyze/load", **kwargs)
    return r.status_code, r.get_json()


print("HIGH-TRAFFIC NOTICE -- TEST SUITE")
keys = eligible_keys()
print(f"\n[0] Environment: {len(keys)} model(s) eligible for the analysis call")
check("at least two models eligible (otherwise the capacity signal is moot)",
      len(keys) >= 2, f"{len(keys)} eligible")

# ── 1. Normal conditions ────────────────────────────────────────────────────
print("\n[1] Normal load")
with mock.patch.dict(ai._state, {}, clear=True):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("endpoint answers 200", code == 200, code)
    check("warning hidden under normal conditions", body["high_load"] is False, body)
    check("no reason given when not high load", body["reason"] is None, body)
    check("reports what it measured", body["measured"].get("models_ready", 0) >= 1,
          body["measured"])

# Healthy pool plus a couple of fast analyses must also stay hidden.
with mock.patch.dict(ai._state, {}, clear=True):
    analysis_mod.reset_recent_analysis_times()
    for s in (2.4, 2.7, 3.1):
        analysis_mod._record_analysis_seconds(s)
    code, body = load()
    check("fast recent analyses keep it hidden", body["high_load"] is False,
          body["measured"])

# ── 2. Genuinely saturated pool ─────────────────────────────────────────────
print("\n[2] Genuine high load: every analysis-capable model unavailable")
saturated = {k: state_entry(t, cooling=True) for k, t in keys}
with mock.patch.dict(ai._state, saturated, clear=True):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("warning shown when all models are in back-off", body["high_load"] is True, body)
    check("reason is the capacity signal", body["reason"] == "ai_capacity", body["reason"])
    check("ready count is zero", body["measured"]["models_ready"] == 0, body["measured"])

exhausted = {k: state_entry(t, exhausted=True) for k, t in keys}
with mock.patch.dict(ai._state, exhausted, clear=True):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("warning shown when every bucket is out of observed headroom",
          body["high_load"] is True and body["reason"] == "ai_capacity", body)

# ── 3. One model still available -> NOT high load ───────────────────────────
print("\n[3] Partial saturation is not high load")
partial = {k: state_entry(t, cooling=True) for k, t in keys[1:]}
with mock.patch.dict(ai._state, partial, clear=True):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("one usable model keeps the warning hidden", body["high_load"] is False,
          body["measured"])

# ── 4. Measured latency ─────────────────────────────────────────────────────
print("\n[4] Genuine high load: recent analyses actually ran slow")
with mock.patch.dict(ai._state, {}, clear=True):
    analysis_mod.reset_recent_analysis_times()
    for s in (18.0, 21.5, 16.0):
        analysis_mod._record_analysis_seconds(s)
    code, body = load()
    check("warning shown on slow measured median", body["high_load"] is True, body)
    check("reason is the latency signal", body["reason"] == "slow_recent", body["reason"])
    check("median is reported", body["measured"]["recent_median_seconds"] >= 14, body["measured"])

    # Below the sample floor: one slow outlier must not trip it.
    analysis_mod.reset_recent_analysis_times()
    analysis_mod._record_analysis_seconds(40.0)
    code, body = load()
    check("a single slow analysis does not trip it", body["high_load"] is False,
          body["measured"])

# ── 5. Nothing invented, nothing random ─────────────────────────────────────
print("\n[5] Deterministic, never probabilistic")
with mock.patch.dict(ai._state, {}, clear=True):
    analysis_mod.reset_recent_analysis_times()
    answers = {json.dumps(load()[1], sort_keys=True) for _ in range(30)}
    check("30 identical calls give exactly one answer", len(answers) == 1,
          f"{len(answers)} distinct")
with mock.patch.dict(ai._state, saturated, clear=True):
    analysis_mod.reset_recent_analysis_times()
    answers = {json.dumps(load()[1], sort_keys=True) for _ in range(30)}
    check("same under high load", len(answers) == 1, f"{len(answers)} distinct")

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "workspace.html"), encoding="utf-8").read()
start = src.find("function showUploadModal")
body_js = src[start:start + 2600]
check("no randomness in the loading UI's notice logic",
      "Math.random" not in body_js and "Math.random" not in src[src.find("uploadLoadNotice"):src.find("uploadLoadNotice") + 1200])
check("notice markup starts hidden",
      'id="uploadLoadNotice"' in src and 'id="uploadLoadNotice" role="status" style="display:none;' in src)
check("notice is gated on an explicit true from the server",
      "d.high_load === true" in src)
check("copy is exactly the approved wording",
      "High traffic right now" in src
      and "Analysis may take a little longer than usual. Thanks for your patience." in src)
check("no fabricated audience claims in the notice",
      not any(p in src[src.find("uploadLoadNotice"):src.find("uploadLoadNotice") + 1200]
              for p in ("people are", "users are", "in queue", "position", "others are")))

# ── 6. Graceful fallback ────────────────────────────────────────────────────
print("\n[6] Graceful fallback")
with mock.patch.object(ai, "pool_status", side_effect=RuntimeError("boom")):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("signal failure -> 200 and hidden", code == 200 and body["high_load"] is False, body)

with mock.patch.dict(os.environ, {}, clear=True):
    analysis_mod.reset_recent_analysis_times()
    code, body = load()
    check("no providers configured -> hidden, not busy",
          code == 200 and body["high_load"] is False, body)

# ── 7. The analysis itself is unchanged ─────────────────────────────────────
print("\n[7] Analysis behaviour unchanged")
FAKE = json.dumps({
    "overall_score": 74,
    "dimension_scores": {"clarity": 70, "experience": 75, "skills": 72,
                         "ats_readiness": 80, "impact": 68, "completeness": 77},
    "summary": "Solid mid-level profile.",
    "strengths": ["Clear structure"],
    "weaknesses": ["Few quantified results"],
    "suggestions": ["Add metrics to recent roles"],
    "suggested_keywords": ["Python"],
})
resume = b"Jane Doe\nSoftware Engineer\nBuilt services in Python and Postgres.\nEducation: B.Tech\n"
analysis_mod.reset_recent_analysis_times()
with mock.patch.object(analysis_mod, "call_groq", return_value=FAKE):
    r = client.post("/api/analyze",
                    data={"resume": (io.BytesIO(resume), "resume.txt")},
                    content_type="multipart/form-data")
    payload = r.get_json() or {}
check("analysis still returns 200 with a real score",
      r.status_code == 200 and payload.get("overall_score") == 74,
      f"{r.status_code} {payload.get('overall_score')}")
check("analysis response carries no load fields",
      "high_load" not in payload and "measured" not in payload)
code, body = load()
check("a completed analysis feeds the latency signal",
      body["measured"].get("samples", 0) >= 1, body["measured"])
check("one fast sample does not raise the warning", body["high_load"] is False, body)

print("\n" + "=" * 50)
print(f"  RESULT: {PASSED} passed, {FAILED} failed")
print("=" * 50)
sys.exit(1 if FAILED else 0)
