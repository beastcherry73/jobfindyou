"""Sweep only candidates not already in the registry, and MERGE the hits.

build_ats_registry.py rewrites the whole registry from one sweep, so a single
transient failure on an existing employer drops it. For growing the registry
that is the wrong trade: this tests only names that have no board yet and
appends what answers, leaving every existing entry (Workday included) alone.

    python scratch/sweep_new_candidates.py
"""
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ats_candidates import all_names  # noqa: E402
from build_ats_registry import OUT, sweep_company  # noqa: E402


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    with io.open(OUT, encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]
    have = {squash(c.get("candidate") or c.get("company")) for c in companies}
    have_tokens = {(c["platform"], c["token"].lower()) for c in companies}
    names = [(n, r) for n, r in all_names() if squash(n) not in have]
    print("Sweeping %d candidates with no board yet" % len(names), flush=True)
    started, hits = time.time(), []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for i, res in enumerate(pool.map(sweep_company, names), 1):
            if res and (res["platform"], res["token"].lower()) not in have_tokens:
                have_tokens.add((res["platform"], res["token"].lower()))
                hits.append(res)
                print("  [%4d/%d] HIT %-15s %-26s %5d jobs (%s)"
                      % (i, len(names), res["platform"], res["token"],
                         res["jobs"], res["company"]), flush=True)
            elif i % 100 == 0:
                print("  [%4d/%d] ..." % (i, len(names)), flush=True)
    companies.extend(hits)
    data["companies"] = companies
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("\n%.0fs | new boards: %d | new live jobs: %d | registry now %d"
          % (time.time() - started, len(hits), sum(h["jobs"] for h in hits),
             len(companies)))


if __name__ == "__main__":
    main()
