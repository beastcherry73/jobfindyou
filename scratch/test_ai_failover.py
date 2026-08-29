"""AI provider failover -- END-TO-END, through the real routes.

Not a unit test of the router. This drives the REAL /api/analyze route with a
REAL resume; the only thing faked is a provider's transport, forced to answer
429 with genuine rate-limit headers. Providers that are NOT blocked are called
for real, so a pass means a user whose Groq quota is exhausted still gets an
analysis instead of "Analysis Failed".

Needs live keys (GROQ_API_KEY / GEMINI_API_KEY / NVIDIA_API_KEY) in .env, so
this is a live suite like the ATS verifiers, not a CI unit test.

Failover depth differs BY REQUEST SIZE, and that is asserted rather than
glossed over. Measured 2026-08-29: NVIDIA NIM needs 58.4s for the 6000-token
analysis prompt -- past our 40s timeout and past the Vercel function budget --
but 10.4s for the 1500-token match prompt. So:

    big analysis call  ->  Groq -> Gemini             (two deep)
    small JSON calls   ->  Groq -> Gemini -> NVIDIA   (three deep)

Run: python scratch/test_ai_failover.py
"""

import io
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

from backend import create_app                       # noqa: E402
from backend.services import ai                      # noqa: E402

GROQ = "api.groq.com"
GEMINI = "generativelanguage.googleapis.com"

# A REAL resume shape. A one-paragraph blob makes the model answer
# is_resume=false and the route then correctly 400s -- which looks like a
# routing failure when it is actually the resume gate doing its job.
RESUME = b"""Priya Raman
Senior Backend Engineer | priya.raman@example.com | Bengaluru, India

SUMMARY
Backend engineer with 7 years building high-throughput payment services.

EXPERIENCE
Staff Engineer, PayFlow (2021-2026)
- Led migration of a monolith to 12 Go microservices, cutting p99 latency 43%.
- Owned Postgres sharding for 40M rows; zero-downtime cutover.
- Built an idempotent webhook pipeline processing 9M events/day on Kafka.

Backend Engineer, Nimbus (2019-2021)
- Wrote the billing reconciliation service in Python/Flask.
- Cut AWS spend 28% by right-sizing ECS tasks.

SKILLS
Python, Go, Flask, Postgres, Kafka, AWS, Docker, Kubernetes, Terraform, Redis

EDUCATION
B.E. Computer Science, Anna University, 2019
"""

JD = ("Senior Backend Engineer. Python, Flask, PostgreSQL, Kafka, AWS, "
      "Kubernetes. Distributed systems, payments, high scale.")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


class R429:
    """A convincing rate-limit response, headers and all."""

    status_code = 429
    text = json.dumps({"error": {"message": "Rate limit reached: Limit 8000 TPM",
                                 "type": "rate_limit_exceeded"}})
    headers = {
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "58.4s",
        "retry-after": "58",
    }

    def json(self):
        return json.loads(self.text)


def block(hosts):
    """Force the named provider hosts to 429; everything else is called for real.

    Returns (call_log, original_post) -- ALWAYS restore original_post in a
    finally block, or a failure here leaks into the next scenario.
    """
    calls = []
    real_post = ai.http_requests.post

    def fake_post(url, **kw):
        model = (kw.get("json") or {}).get("model", "?")
        if any(h in url for h in hosts):
            calls.append((model, "429 (forced)"))
            return R429()
        r = real_post(url, **kw)
        calls.append((model, r.status_code))
        return r

    ai.http_requests.post = fake_post
    ai._state.clear()      # no leftover cooldowns between scenarios
    return calls, real_post


def _analyze(hosts):
    """POST a real resume through the real route with `hosts` rate-limited."""
    calls, real = block(hosts)
    t = time.time()
    try:
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            r = c.post("/api/analyze", data={
                "resume": (io.BytesIO(RESUME), "priya_raman.txt"),
                "job_description": JD,
            }, content_type="multipart/form-data")
            return r, (r.get_json() or {}), calls, time.time() - t
    finally:
        ai.http_requests.post = real


def scenario_analysis(label, hosts, expect_served):
    print("\n[%s]" % label)
    r, body, calls, elapsed = _analyze(hosts)
    for model, status in calls:
        print(f"    {str(status):14} {model}")
    served = next((m for m, s in calls if s == 200), None)
    print(f"    HTTP {r.status_code} in {elapsed:.1f}s; served by: {served}")

    if not expect_served:
        return r, body, calls, elapsed, served

    jm = body.get("job_match") or {}
    check("a real analysis came back",
          r.status_code == 200
          and isinstance(body.get("overall_score"), int)
          and body.get("overall_score") > 0
          and bool(body.get("strengths")),
          f"score={body.get('overall_score')} "
          f"strengths={len(body.get('strengths') or [])}")
    # job_match is the SECOND json_mode call site in this route, so it proves
    # both JSON paths survived the reroute, not just the first.
    check("the second JSON call site (job match) also came back",
          isinstance(jm.get("match_percent"), int),
          f"match={jm.get('match_percent')} "
          f"keywords={len(jm.get('matching_keywords') or [])}")
    return r, body, calls, elapsed, served


def main():
    # 1. Nothing blocked: the ordinary path still works after wiring json_mode.
    _, _, _, _, served = scenario_analysis(
        "1 BASELINE - every provider available", [], expect_served=True)
    check("baseline is served by Groq",
          bool(served) and "gpt-oss" in (served or ""), str(served))

    # 2. THE POINT OF THE FEATURE: Groq exhausted, a real analysis still lands.
    _, _, _, _, served = scenario_analysis(
        "2 FAILOVER - all six Groq models rate-limited", [GROQ],
        expect_served=True)
    check("analysis rerouted off Groq to another provider",
          bool(served) and "gpt-oss" not in (served or "")
          and "groq" not in (served or ""), str(served))

    # 3. Groq AND Gemini gone. NVIDIA is too slow for a 6000-token prompt, so
    # the honest outcome is a fast clean 502 -- NOT a 40s hang on a model that
    # cannot finish, which would burn the whole request budget.
    r, body, calls, elapsed, _ = scenario_analysis(
        "3 BIG analysis with Groq AND Gemini exhausted", [GROQ, GEMINI],
        expect_served=False)
    slow = [m for m, _ in calls if "nvidia" in m or "mistral" in m]
    check("fails fast instead of hanging on a model that cannot finish in time",
          r.status_code == 502 and elapsed < 40 and not slow,
          f"{elapsed:.1f}s, oversized-model attempts={len(slow)}")
    check("user sees a retry message, not a crash or a fabricated result",
          "unavailable" in (body.get("error") or "").lower(), body.get("error"))

    # 4. The SMALL calls really are three deep: NVIDIA serves the digest.
    print("\n[4] SMALL digest scoring with Groq AND Gemini exhausted")
    try:
        from backend.services import digest
    except ImportError:
        print("    (digest module not present -- skipped)")
    else:
        calls, real = block([GROQ, GEMINI])
        try:
            app = create_app()
            with app.app_context():
                scored = digest.ai_score(
                    [{"id": 1, "title": "Senior Backend Engineer",
                      "company": "PayCo"}],
                    {1: ("We need a backend engineer strong in Python, Flask, "
                         "Postgres, Kafka and AWS to own our payments pipeline.")},
                    RESUME.decode(), ai_limit=1)
        finally:
            ai.http_requests.post = real
        j = scored[0] if scored else {}
        served = next((m for m, s in calls if s == 200), None)
        print(f"    served by: {served}")
        check("digest still scores via NVIDIA when Groq and Gemini are both out",
              bool(j.get("ai_scored"))
              and isinstance(j.get("match_percent"), int)
              and bool(served) and "nvidia" in served,
              f"ai_scored={j.get('ai_scored')} "
              f"match={j.get('match_percent')} by={served}")

    # 5. json_mode must NOT have leaked onto the prose call sites (builder
    # polish, resume generation). A JSON object there would ship a resume with
    # braces in it.
    print("\n[5] TEXT call sites are NOT in JSON mode")
    calls, real = block([])
    try:
        app = create_app()
        with app.app_context():
            out = ai.call_groq("Rewrite this resume bullet to be stronger. "
                               "Return ONLY the bullet: 'did backend work'",
                               max_tokens=300)
    finally:
        ai.http_requests.post = real
    stripped = (out or "").strip()
    safe = stripped[:80].encode("ascii", "replace").decode("ascii")
    print(f"    returned: {safe!r}")
    check("text call returns prose, not a JSON object",
          bool(stripped)
          and not (stripped.startswith("{") and stripped.endswith("}")),
          safe[:60])

    print("\n" + "=" * 62)
    print(f"  {sum(results)} passed, {len(results) - sum(results)} failed")
    print("=" * 62)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
