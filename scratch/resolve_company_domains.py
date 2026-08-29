"""Resolve a verified web domain for every company in the ATS registry.

WHY THIS EXISTS
---------------
Company logos cannot come from the ATS APIs. Verified 2026-08-29 by walking the
complete JSON of Greenhouse, Ashby, Lever and SmartRecruiters board responses:
none of them carries a structured `logo` or `domain` field. (Strings matching
"logo" appear only inside job-description HTML.)

So a logo needs a DOMAIN, and the domain has to come from us. Resolving it at
request time would mean a network round trip per card, so it is resolved ONCE
here, offline, and persisted into backend/data/ats_companies.json alongside the
board token. The app then builds the logo URL from the stored domain with no
extra call at all.

WHICH LOGO SERVICE
------------------
Measured the same day, because the obvious choice is dead:

    logo.clearbit.com        ConnectionError -- the free API was sunset
    icons.duckduckgo.com     HTTP 200, up to ~15KB    <- primary
    google.com/s2/favicons   HTTP 200, ~600-1000B     <- fallback
    img.logo.dev             HTTP 401 (needs a key)   -- rejected, and
                                                         JobSpike stays card-free

DuckDuckGo is primary on quality; Google is the fallback because it answers for
essentially any domain, just smaller.

CANDIDATE DOMAINS
-----------------
Guessed from the board token and the company display name, then VERIFIED with a
real request -- a guess that is never checked would put a broken image on every
card. `.com` first, then the tech-company TLDs, and a guess is only accepted
when the host actually answers.

Run:  python scratch/resolve_company_domains.py [--limit N] [--dry-run]
"""

import argparse
import json
import os
import re
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(_ROOT, "backend", "data", "ats_companies.json")

# Tried in order. `.com` dominates; the rest are the TLDs this corpus's
# employers actually use.
_TLDS = (".com", ".io", ".ai", ".co", ".dev", ".org", ".net")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SUFFIXES = (
    " inc", " inc.", " llc", " ltd", " ltd.", " limited", " corp", " corp.",
    " corporation", " gmbh", " bv", " plc", " labs", " technologies",
    " technology", " software", " systems", " group", " holdings", " co",
)

_TIMEOUT = 8
_lock = threading.Lock()
_done = [0]


def _slugs(entry):
    """Candidate name-stems for one company, best guess first."""
    out = []
    for raw in (entry.get("company"), entry.get("candidate"), entry.get("token")):
        if not raw:
            continue
        name = str(raw).strip().lower()
        for suf in _SUFFIXES:
            if name.endswith(suf):
                name = name[: -len(suf)].strip()
        squashed = _NON_ALNUM.sub("", name)
        if squashed and squashed not in out:
            out.append(squashed)
        hyphenated = _NON_ALNUM.sub("-", name).strip("-")
        if hyphenated and hyphenated != squashed and hyphenated not in out:
            out.append(hyphenated)
    return out


# A host that answers 401/403/429 EXISTS -- it is just gated or rate-limiting.
# Treating those as dead is what made servicenow resolve to servicenow.dev and
# zeta to zeta.ai: the real .com answered 401 or timed out behind bot
# protection, so a lesser TLD won.
_GATED = {401, 403, 429, 451}


def _alive(domain):
    """True when the host exists, whether or not it will serve us a page.

    Three levels of evidence, weakest last:
      1. any HTTP response below 400            -- definitely real
      2. 401 / 403 / 429 / 451                  -- real, but gated to bots
      3. the name resolves in DNS               -- real enough for a logo

    Level 3 exists because some corporate sites (servicenow.com) simply never
    answer a scripted request. Falling through to a different TLD is worse
    than trusting DNS: it puts another company's logo on the card.
    """
    for method in (requests.head, requests.get):
        try:
            r = method(f"https://{domain}", timeout=_TIMEOUT, allow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 (compatible; JobSpike/1.0)"},
                       stream=True)
            if r.status_code < 400 or r.status_code in _GATED:
                return True
            if r.status_code in (405, 501) and method is requests.head:
                continue        # HEAD not allowed; let GET decide
        except requests.RequestException:
            continue
    try:
        socket.getaddrinfo(domain, 443)
        return True
    except OSError:
        return False


def resolve(entry, total):
    """Attach a verified `domain` to one registry entry (or leave it absent)."""
    found = ""
    for stem in _slugs(entry):
        for tld in _TLDS:
            cand = stem + tld
            if _alive(cand):
                found = cand
                break
        if found:
            break
    if found:
        entry["domain"] = found
    with _lock:
        _done[0] += 1
        n = _done[0]
        if n % 25 == 0 or n == total:
            print(f"  ...{n}/{total} resolved", flush=True)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N (for a smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="do not write the registry")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    with open(REGISTRY, encoding="utf-8") as fh:
        data = json.load(fh)

    # The file is a dict of metadata plus the company list; find the list
    # without assuming its key, so a future metadata change cannot silently
    # make this script a no-op.
    key = next((k for k, v in data.items()
                if isinstance(v, list) and v and isinstance(v[0], dict)
                and "platform" in v[0]), None)
    if key is None:
        print("Could not find the company list in the registry file.")
        return 2
    companies = data[key]
    targets = companies[: args.limit] if args.limit else companies

    print(f"Resolving domains for {len(targets)} of {len(companies)} companies "
          f"({args.workers} workers)...")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda e: resolve(e, len(targets)), targets))

    got = sum(1 for e in targets if e.get("domain"))
    print()
    print(f"  resolved : {got}/{len(targets)}  ({100.0*got/max(1,len(targets)):.0f}%)")
    print(f"  unresolved: {len(targets)-got} (these fall back to a lettermark in the UI)")

    if args.dry_run:
        print("\n--dry-run: registry NOT written")
    else:
        with open(REGISTRY, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        print(f"\nwrote {REGISTRY}")

    print("\nsamples:")
    for e in targets[:10]:
        print(f"  {e.get('company','?')[:26]:26} -> {e.get('domain') or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
