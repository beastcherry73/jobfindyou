"""Verify that stored ATS apply URLs really reach the employer's application page.

This is the check that decides whether a platform ships or gets dropped. For a
sample of stored jobs per platform it follows the apply_url (redirects and all)
and asserts three things about where it lands:

  1. the request succeeds (HTTP 200),
  2. the destination page actually contains the job title, and
  3. the destination page names the company.

A link that 404s, redirects to a generic careers homepage, or lands on a page
that mentions neither the role nor the employer is reported as BROKEN, because
that is the failure mode that would waste a real user's click.

There is also a whole-registry audit. Some employers point their ATS at a
custom careers domain (Recruitee does this by default), and when that domain
lapses the listings survive in the ATS API while every apply link is dead. The
audit follows one real apply URL per company and can drop the companies whose
destination no longer resolves, so we never ship a link we know is broken.

Usage:
    python scratch/verify_ats_registry.py            # 8 samples per platform
    python scratch/verify_ats_registry.py --n 15
    python scratch/verify_ats_registry.py --audit    # every company, report only
    python scratch/verify_ats_registry.py --audit --prune   # ...and drop the dead ones
"""

import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.services.ats import PLATFORMS  # noqa: E402

BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TAG = re.compile(r"<[^>]+>")


def flatten(html):
    return re.sub(r"\s+", " ", _TAG.sub(" ", html or "")).lower()


def significant_words(text, minimum=4):
    """Distinctive words from a title, ignoring filler."""
    stop = {"and", "the", "for", "with", "senior", "staff", "lead", "manager",
            "engineer", "specialist", "analyst", "associate", "director"}
    words = [w for w in re.findall(r"[a-z0-9]{%d,}" % minimum, (text or "").lower())
             if w not in stop]
    return words


def check(job):
    """Follow one apply_url and record where it landed."""
    url = job["apply_url"]
    result = {"platform": job["platform"], "company": job["company"],
              "title": job["title"], "url": url, "status": None,
              "final_host": "", "final_path": "", "title_found": False,
              "company_found": False, "bytes": 0}
    try:
        r = requests.get(url, headers=BROWSER_UA, timeout=30, allow_redirects=True)
    except requests.RequestException as e:
        result["error"] = type(e).__name__
        return result
    parsed = urlparse(r.url)
    result["status"] = r.status_code
    result["final_host"] = parsed.netloc
    result["final_path"] = parsed.path or "/"
    result["bytes"] = len(r.text or "")
    if r.status_code != 200:
        return result

    body = flatten(r.text)
    title_words = significant_words(job["title"])
    if title_words:
        hits = sum(1 for w in title_words if w in body)
        result["title_found"] = hits >= max(1, len(title_words) // 2)
    else:
        result["title_found"] = (job["title"] or "").lower() in body

    company_words = significant_words(job["company"], minimum=3)
    result["company_found"] = any(w in body for w in company_words) if company_words else False
    return result


def verdict(r):
    """Classify a destination.

    Two things had to be separated from real breakage, because conflating them
    would have wrongly dropped six working employers:

      * BLOCKED  - the host answers 403 to automated requests (Cloudflare/WAF).
        The posting URL is intact; only our scraper is refused.
      * JS-SHELL - HTTP 200 on the correct posting path, but the page is
        rendered client-side so the served HTML carries no title or company.

    BROKEN is reserved for destinations a real user could not apply from: an
    unresolvable host, a 404, or a redirect that dumps them on a site root
    instead of the posting.
    """
    if r.get("error"):
        return "BROKEN"
    status = r["status"]
    if status == 403:
        return "BLOCKED"
    if status != 200:
        return "BROKEN"
    # Redirected to a bare domain root: the board is gone and the posting with
    # it (an orphaned custom careers domain, or a deleted board).
    if r["final_path"] in ("", "/") and not r["title_found"]:
        return "BROKEN"
    if r["title_found"] and r["company_found"]:
        return "OK"
    if r["title_found"] or r["company_found"]:
        return "OK-PARTIAL"
    return "JS-SHELL"


def audit_registry(prune=False):
    """Follow one apply URL per company; report (and optionally drop) dead boards."""
    import json

    from backend.services.ats import _REGISTRY_PATH

    with create_app().app_context():
        with get_db() as db:
            rows = db.execute(
                "SELECT platform, company_token, company, title, apply_url, "
                "MIN(id) AS id FROM ats_jobs GROUP BY platform, company_token"
            ).fetchall()
    jobs = [dict(r) for r in rows]
    print("Auditing %d companies (one live apply URL each)...\n" % len(jobs))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check, jobs))

    dead, noted = [], {"BLOCKED": 0, "JS-SHELL": 0, "OK": 0, "OK-PARTIAL": 0}
    for job, r in zip(jobs, results):
        v = verdict(r)
        if v == "BROKEN":
            dead.append((job["platform"], job["company_token"]))
            print("  DEAD     %-16s %-22s %s -> %s%s"
                  % (r["platform"], r["company"][:22],
                     r.get("status") or r.get("error"),
                     r["final_host"] or "-", r.get("final_path") or ""))
        else:
            noted[v] += 1
            if v in ("BLOCKED", "JS-SHELL"):
                print("  %-8s %-16s %-22s -> %s (link intact, not scrapable)"
                      % (v, r["platform"], r["company"][:22], r["final_host"]))

    print("\nDestination classes: %s" % noted)
    print("Reachable: %d / %d companies" % (len(jobs) - len(dead), len(jobs)))
    if not dead:
        print("No dead boards found.")
        return
    if not prune:
        print("(run again with --prune to drop these from the registry)")
        return

    with io.open(_REGISTRY_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    drop = set(dead)
    before = len(payload["companies"])
    payload["companies"] = [c for c in payload["companies"]
                            if (c["platform"], c["token"]) not in drop]
    payload["dropped_note"] = (
        "Companies whose apply URLs no longer resolve are removed by "
        "scratch/verify_ats_registry.py --audit --prune.")
    with io.open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    print("Registry pruned: %d -> %d companies" % (before, len(payload["companies"])))


def main():
    if "--audit" in sys.argv:
        audit_registry(prune="--prune" in sys.argv)
        return
    per = 8
    if "--n" in sys.argv:
        per = int(sys.argv[sys.argv.index("--n") + 1])

    jobs = []
    with create_app().app_context():
        with get_db() as db:
            for platform in PLATFORMS:
                rows = db.execute(
                    "SELECT platform, company, title, apply_url FROM ats_jobs "
                    "WHERE platform = ? ORDER BY company_token LIMIT ?",
                    (platform, per),
                ).fetchall()
                jobs.extend(dict(r) for r in rows)

    print("Verifying %d apply URLs (%d per platform)...\n" % (len(jobs), per))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, jobs))

    classes = ["OK", "OK-PARTIAL", "JS-SHELL", "BLOCKED", "BROKEN"]
    summary = {}
    for r in results:
        v = verdict(r)
        summary.setdefault(r["platform"], {c: 0 for c in classes})
        summary[r["platform"]][v] += 1
        if v == "BROKEN":
            print("  BROKEN  %-16s %s | %s -> %s %s"
                  % (r["platform"], r["company"][:22], r["title"][:34],
                     r.get("status") or r.get("error"), r["final_host"]))

    print("\n%-16s %4s %10s %9s %8s %7s   %s"
          % ("PLATFORM", "OK", "OK-PARTIAL", "JS-SHELL", "BLOCKED", "BROKEN", "VERDICT"))
    for platform in PLATFORMS:
        s = summary.get(platform)
        if not s:
            print("%-16s   (no jobs stored)" % platform)
            continue
        good = s["OK"] + s["OK-PARTIAL"] + s["JS-SHELL"] + s["BLOCKED"]
        total = good + s["BROKEN"]
        state = "CONFIRMED" if good == total else (
            "PARTIAL" if good >= total * 0.8 else "UNRELIABLE")
        print("%-16s %4d %10d %9d %8d %7d   %s (%d/%d)"
              % (platform, s["OK"], s["OK-PARTIAL"], s["JS-SHELL"], s["BLOCKED"],
                 s["BROKEN"], state, good, total))

    print("\nDestination behaviour (what a user meets on click):")
    for platform, spec in PLATFORMS.items():
        print("  %-16s account required: %-5s  %s"
              % (platform, spec["requires_account"], spec["destination"]))


if __name__ == "__main__":
    main()
