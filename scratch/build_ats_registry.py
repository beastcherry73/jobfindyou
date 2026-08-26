"""Empirically build the keyless-ATS company registry.

Nothing here is assumed. Every candidate slug in ats_candidates.py is tested
against EVERY platform's public, unauthenticated board endpoint, and a company
is written to the registry only if that endpoint actually answers with live job
data. Platforms that need a key are excluded by construction (Teamtailor was
tested and rejected on exactly that basis -- see backend/services/ats.py).

Two guards keep the registry honest:

  * No early exit. Every platform is tested for every candidate, so a company
    is never mis-attributed to whichever platform happened to be checked first.
  * Name verification. Where a platform reports the board owner's name
    (Greenhouse, SmartRecruiters, Workable, Recruitee), it is compared with the
    candidate name; a clear mismatch is rejected rather than guessed at.

Output: backend/data/ats_companies.json  (consumed by backend/services/ats.py)

Usage:
    python scratch/build_ats_registry.py            # full sweep, writes registry
    python scratch/build_ats_registry.py --dry-run  # sweep, print, write nothing
"""

import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ats_candidates import all_names  # noqa: E402
from backend.services.ats import PLATFORMS, board_url, HTTP_HEADERS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "backend", "data", "ats_companies.json")
TIMEOUT = 20

# How each platform reports the board owner's name, where it does at all.
# Lever, Ashby and Breezy expose no owner name in the board payload, so their
# hits carry the candidate name and are checked by the apply-URL verifier
# (scratch/verify_ats_registry.py) instead.
OWNER_NAME = {
    "greenhouse": lambda payload, rows: (rows[0] or {}).get("company_name"),
    "smartrecruiters": lambda payload, rows: ((rows[0] or {}).get("company") or {}).get("name"),
    "workable": lambda payload, rows: payload.get("name") if isinstance(payload, dict) else None,
    "recruitee": lambda payload, rows: (rows[0] or {}).get("company_name"),
}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def name_matches(candidate, reported):
    """True when the board owner plausibly IS the candidate company."""
    if not reported:
        return True                       # platform reports no name: can't judge
    a, b = squash(candidate), squash(reported)
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    # "Bosch" vs "Bosch Group", "Wix" vs "Wix.com" -- share the leading token.
    at = [w for w in re.findall(r"[a-z0-9]+", candidate.lower()) if len(w) > 2]
    bt = [w for w in re.findall(r"[a-z0-9]+", reported.lower()) if len(w) > 2]
    return bool(at and bt and at[0] == bt[0])


def slugs_for(name, platform):
    """Slug variants to try for a company name on a given platform."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return []
    lower = "".join(words).lower()
    hyphen = "-".join(w.lower() for w in words)
    if platform == "smartrecruiters":
        # SmartRecruiters identifiers are CamelCase display names, sometimes
        # with a corporate or numeric suffix (verified: "BoschGroup", "Ubisoft2").
        camel = "".join(w[0].upper() + w[1:] for w in words)
        out = [camel, camel + "Group", camel + "Inc", camel + "1", camel + "2"]
    else:
        out = [lower]
        if hyphen != lower:
            out.append(hyphen)
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def test(platform, token, candidate, session):
    """Return a registry entry if this token is a live, correctly-owned board."""
    try:
        r = session.get(board_url(platform, token), headers=HTTP_HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    rows = PLATFORMS[platform]["rows"](payload)
    if not rows:
        return None
    reported = None
    if platform in OWNER_NAME:
        try:
            reported = OWNER_NAME[platform](payload, rows)
        except Exception:
            reported = None
    if not name_matches(candidate, reported):
        return None
    total = PLATFORMS[platform]["total"](payload, rows)
    return {
        "platform": platform,
        "token": token,
        "jobs": int(total or len(rows)),
        "owner_name": (reported or "").strip(),
        "sample_url": PLATFORMS[platform]["apply_url"](rows[0], token) or "",
    }


def sweep_company(item):
    """Test a candidate against every platform; return the best confirmed board."""
    name, region = item
    session = requests.Session()
    hits = []
    for platform in PLATFORMS:
        for token in slugs_for(name, platform):
            got = test(platform, token, name, session)
            if got:
                hits.append(got)
                break                     # one token per platform is enough
    if not hits:
        return None
    # Prefer a board whose owner name the platform actually confirmed, then the
    # one carrying more live jobs.
    hits.sort(key=lambda h: (0 if h["owner_name"] else 1, -h["jobs"]))
    best = hits[0]
    best.update({"company": best["owner_name"] or name, "region": region,
                 "candidate": name})
    return best


def main():
    dry = "--dry-run" in sys.argv
    names = all_names()
    print("Sweeping %d candidate companies across %d keyless platforms: %s"
          % (len(names), len(PLATFORMS), ", ".join(PLATFORMS)))
    started = time.time()
    hits = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for i, res in enumerate(pool.map(sweep_company, names), 1):
            if res:
                hits.append(res)
                print("  [%3d/%d] HIT  %-16s %-26s %5d jobs  (%s)"
                      % (i, len(names), res["platform"], res["token"],
                         res["jobs"], res["company"]))
            elif i % 50 == 0:
                print("  [%3d/%d] ..." % (i, len(names)))
    elapsed = time.time() - started

    by_platform, by_region, total_jobs = {}, {}, 0
    for h in hits:
        by_platform[h["platform"]] = by_platform.get(h["platform"], 0) + 1
        by_region[h["region"]] = by_region.get(h["region"], 0) + 1
        total_jobs += h["jobs"]

    print("\nSwept in %.0fs" % elapsed)
    print("Confirmed companies : %d / %d candidates" % (len(hits), len(names)))
    print("Total live jobs     : %d" % total_jobs)
    print("By platform         : %s" % by_platform)
    print("By region           : %s" % by_region)

    if dry:
        print("\n--dry-run: registry not written.")
        return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Every entry was verified live against the platform's public, "
                "keyless board endpoint by scratch/build_ats_registry.py.",
        "companies": sorted(hits, key=lambda h: (h["platform"], h["token"])),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    print("\nWrote %s" % OUT)


if __name__ == "__main__":
    main()
