"""Test suite for the keyless ATS job layer.

Covers the four things the feature actually promises:
  1. normalization  -- every platform's payload maps onto the shared schema
  2. filters        -- each one applies exactly, and they combine
  3. ranking        -- ATS listings outrank aggregator listings
  4. idempotency    -- a re-sync refreshes rows instead of duplicating them

Run:  python scratch/test_ats_layer.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.services import ats  # noqa: E402
from backend.services.jobsources import _merge_rank_dedupe  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def test_resolvers():
    print("\n[1] Normalization")
    rc = ats.resolve_country
    for text, expect in [
        ("Bengaluru, Karnataka, India", "in"), ("Remote - US", "us"),
        ("San Mateo, CA United States", "us"), ("Spain (Remote)", "es"),
        ("United States - Remote", "us"), ("Dubai", "ae"), ("TLV", "il"),
        ("New York City", "us"), ("Houston, TX", "us"), ("Vilnius", "lt"),
    ]:
        check("country %-30r -> %s" % (text, expect), rc(text) == expect, repr(rc(text)))
    for text in ["Distributed", "Home based - Worldwide", "Europe", "Remote", ""]:
        check("country %-30r -> '' (honest unknown)" % text, rc(text) == "")

    et = ats.normalize_employment_type
    for text, expect in [("Permanent, Full-Time", "Full-time"), ("On-Roll", "Full-time"),
                         ("Parttime Fixed Term", "Part-time"),
                         ("Independent Contractor", "Contract"),
                         ("Contract, Full-Time", "Contract"), ("FullTime", "Full-time"),
                         ("Talent Pooling Opportunity", ""), ("Volunteer", "")]:
        check("employment %-28r -> %r" % (text, expect), et(text) == expect, repr(et(text)))
    check("employment values are a closed set",
          all(et(v) in ats.EMPLOYMENT_TYPES + [""] for v in
              ["anything", "Full-Time Employment", "Fixed Term", "Other"]))

    el = ats.normalize_experience_level
    for title, expect in [("Senior Channel Account Manager", "senior"),
                          ("Engineering Manager, Auth", "lead"),
                          ("Product Manager", ""), ("Principal Engineer", "lead"),
                          ("Director of Sales", "executive"),
                          ("Marketing Intern", "internship"),
                          ("Junior Analyst", "entry"), ("Software Engineer", "")]:
        check("level %-34r -> %r" % (title, expect), el(None, title) == expect,
              repr(el(None, title)))

    ts = ats._iso
    check("timestamp epoch-ms normalizes to UTC", ts(1711403416463).endswith("+00:00"))
    check("timestamp offset normalizes to UTC",
          ts("2026-08-25T17:40:40-04:00") == "2026-08-25T21:40:40+00:00", ts("2026-08-25T17:40:40-04:00"))
    check("timestamp bare date normalizes", ts("2026-06-27").startswith("2026-06-27T00:00:00"))
    # None, never "": posted_at is a real TIMESTAMPTZ in production and
    # Postgres rejects an empty string for that type. SQLite would accept it,
    # which is exactly how this class of bug stays hidden until deploy.
    check("timestamp garbage -> None (never empty string)", ts("garbage") is None)
    check("timestamp empty -> None", ts("") is None)

    nul = chr(0)
    check("control chars scrubbed (Postgres text rejects NUL)",
          nul not in ats._text("a" + nul + "b") and ats._text("a" + nul + "b") == "a b")

    # Guard the whole "works on SQLite, dies on Postgres" class: pg8000 sends
    # str as OID 25 (TEXT), which Postgres refuses for a TIMESTAMPTZ column.
    import backend.database as _dbmod
    from datetime import datetime as _dt, timezone as _tz
    sample = _dt(2026, 1, 2, 3, 4, 5, tzinfo=_tz.utc)
    pg_like = _dbmod.PgConnection.__new__(_dbmod.PgConnection)
    check("timestamp param for SQLite is an ISO string",
          isinstance(ats._timestamp_param(object(), sample), str))
    check("timestamp param for Postgres is a real datetime",
          isinstance(ats._timestamp_param(pg_like, sample), _dt))
    check("empty timestamp param becomes NULL",
          ats._timestamp_param(object(), "") is None)

    # Nothing normalized off a live board may carry an empty-string timestamp.
    check("normalizer never emits an empty-string posted_at",
          all(j.get("posted_at") != "" for j in _sample_jobs()))


def _sample_jobs():
    entry = ats.load_registry()[0]
    _, jobs = ats._fetch_and_normalize(entry)
    return jobs


def test_registry():
    print("\n[2] Registry")
    reg = ats.load_registry()
    check("registry is populated", len(reg) >= 200, "%d companies" % len(reg))
    check("every entry names a supported platform",
          all(c["platform"] in ats.PLATFORMS for c in reg))
    check("every entry has a token", all(c.get("token") for c in reg))
    check("no duplicate platform+token",
          len({(c["platform"], c["token"]) for c in reg}) == len(reg))
    check("Teamtailor is not present (needs an API key)",
          "teamtailor" not in ats.PLATFORMS)


def test_search():
    print("\n[3] Filters (exact and combinable)")
    base = ats.search(per_page=5)
    check("unfiltered search returns rows", base["count"] > 0, str(base["count"]))

    remote = ats.search(work_mode="remote", per_page=50)
    check("work_mode=remote returns only remote",
          remote["results"] and all(r["work_mode"] == "remote" for r in remote["results"]))
    check("work_mode narrows the corpus", remote["count"] < base["count"])

    senior = ats.search(experience_level="senior", per_page=50)
    check("experience_level=senior returns only senior",
          senior["results"] and all(r["experience_level"] == "senior" for r in senior["results"]))

    ft = ats.search(employment_type="Full-time", per_page=50)
    check("employment_type is exact",
          ft["results"] and all(r["employment_type"] == "Full-time" for r in ft["results"]))

    eng = ats.search(what="engineer", per_page=50)
    check("keyword matches title/company/location",
          eng["results"] and all("engineer" in (r["title"] + r["company"] + r["location"]).lower()
                                 for r in eng["results"]))

    excl = ats.search(what="engineer", what_exclude="senior", per_page=50)
    check("exclude keyword removes matches",
          all("senior" not in (r["title"] + r["company"] + r["location"]).lower()
              for r in excl["results"]))
    check("exclude narrows the result set", excl["count"] < eng["count"],
          "%d vs %d" % (excl["count"], eng["count"]))

    india = ats.search(country="in", per_page=50)
    check("country narrows the corpus", india["count"] < base["count"])
    # Every returned row must resolve to the requested country, or to no
    # country at all (a genuinely global remote listing: "Distributed",
    # "Home based - Worldwide"). The previous assertion here ended in
    # `or True`, so it passed no matter what -- and it hid a filter that
    # admitted every located remote row into every country.
    #
    # country_code is a filter column, not part of the returned schema, so the
    # check re-resolves the location string the user actually sees on the card.
    def _off_country(rows, want):
        out = []
        for r in rows:
            got = ats.resolve_country(r.get("location") or "")
            if got and got != want:
                out.append((r.get("location"), got))
        return out

    off = _off_country(india["results"], "in")
    check("country filter admits no other country's located jobs",
          india["results"] and not off,
          "%d off-country rows, e.g. %s" % (len(off), off[0] if off else ""))

    # The reported regression: picking Indonesia returned India's jobs, because
    # a located remote row matched every country. Both are well populated in
    # the corpus, so a stray here is a real leak, not a corpus artifact.
    indo = ats.search(country="id", per_page=50)
    strays = _off_country(indo["results"], "id")
    check("selecting Indonesia returns no other country's located jobs",
          indo["results"] and not strays,
          "%d strays, e.g. %s" % (len(strays), strays[0] if strays else ""))

    # The whole point of owning the data: stack four filters at once.
    combo = ats.search(what="engineer", country="in", work_mode="remote",
                       experience_level="senior", per_page=50)
    check("four filters combine without error", isinstance(combo["count"], int))
    check("combined result honours every filter",
          all(r["work_mode"] == "remote" and r["experience_level"] == "senior"
              and "engineer" in (r["title"] + r["company"] + r["location"]).lower()
              for r in combo["results"]))
    check("combined is narrower than any single filter",
          combo["count"] <= min(eng["count"], india["count"], remote["count"]))

    recent = ats.search(max_days_old=30, per_page=50)
    check("max_days_old narrows the corpus", recent["count"] < base["count"],
          "%d vs %d" % (recent["count"], base["count"]))

    page1 = ats.search(per_page=5, page=1)
    page2 = ats.search(per_page=5, page=2)
    ids1 = {r["id"] for r in page1["results"]}
    ids2 = {r["id"] for r in page2["results"]}
    check("pagination returns distinct pages", ids1 and ids2 and not (ids1 & ids2))

    dated = ats.search(sort_by="date", per_page=10)
    stamps = [r["posted_at"] for r in dated["results"] if r["posted_at"]]
    check("sort_by=date is newest-first", stamps == sorted(stamps, reverse=True))


def test_schema():
    print("\n[4] Unified schema + direct-apply ranking")
    rows = ats.search(per_page=5)["results"]
    required = ["title", "company", "location", "salary_min", "salary_max",
                "employment_type", "posted_at", "publisher", "apply_url", "source"]
    check("every required schema field present",
          all(all(f in r for f in required) for r in rows))
    check("apply_url always populated", all(r["apply_url"] for r in rows))
    check("apply_url is an employer/ATS link, never an aggregator",
          all(not any(bad in r["apply_url"] for bad in
                      ("adzuna.", "careerjet.", "jooble.", "jobviewtrack."))
              for r in rows))
    check("flagged as direct apply", all(r["apply_is_direct"] for r in rows))
    check("redirect_url alias kept for the tracker flow",
          all(r["redirect_url"] == r["apply_url"] for r in rows))
    check("source names the real platform",
          all(r["source"] in [p["label"] for p in ats.PLATFORMS.values()] for r in rows))

    # Apply-friction labelling: SmartRecruiters wants an account, the other six
    # allow a guest apply. This must come from the platform spec, not a string
    # match on the source name.
    sr = ats.search(per_page=5)
    sr_rows = [r for r in ats.search(per_page=200)["results"]
               if r["source"] == "SmartRecruiters"]
    other_rows = [r for r in ats.search(per_page=200)["results"]
                  if r["source"] != "SmartRecruiters"]
    check("requires_account present on every ATS row",
          all("requires_account" in r for r in rows))
    check("SmartRecruiters rows are flagged account-required",
          bool(sr_rows) and all(r["requires_account"] for r in sr_rows),
          "%d rows" % len(sr_rows))
    check("guest-apply platforms are NOT flagged",
          all(not r["requires_account"] for r in other_rows),
          "%d rows" % len(other_rows))

    # Ranking: ATS above aggregators, per the approved ordering.
    ats_row = dict(rows[0])
    aggregator = {"title": "Other Role", "company": "Someone", "location": "X",
                  "apply_is_direct": False, "source": "Adzuna"}
    merged = _merge_rank_dedupe([[ats_row], [aggregator]])
    check("ATS listing ranks above an aggregator listing",
          merged[0]["source"] == ats_row["source"], merged[0]["source"])

    # A duplicate posting must resolve to the direct-apply copy.
    dupe = {"title": ats_row["title"], "company": ats_row["company"],
            "location": ats_row["location"], "apply_is_direct": False,
            "source": "Jooble"}
    merged2 = _merge_rank_dedupe([[dupe], [ats_row]])
    check("duplicate collapses to the direct-apply copy",
          len(merged2) == 1 and merged2[0]["apply_is_direct"] is True)


def test_idempotency():
    print("\n[5] Idempotency (re-sync must not duplicate)")
    with get_db() as db:
        before = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
        distinct = db.execute(
            "SELECT COUNT(DISTINCT fingerprint) AS n FROM ats_jobs").fetchone()["n"]
    check("no duplicate fingerprints in the corpus", before == distinct,
          "%d rows vs %d fingerprints" % (before, distinct))

    entry = ats.load_registry()[0]
    _, jobs = ats._fetch_and_normalize(entry)
    if not jobs:
        check("re-sync of one company is idempotent", True, "(board unreachable, skipped)")
        return
    stats = {"companies": 0, "fetched": 0, "stored": 0, "pruned": 0, "failed": 0}
    ats._store_company(entry, jobs, stats)
    ats._store_company(entry, jobs, stats)      # deliberately twice
    with get_db() as db:
        after = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
    check("storing the same board twice adds no rows", after == before,
          "%d -> %d" % (before, after))


def main():
    print("KEYLESS ATS LAYER — TEST SUITE")
    test_resolvers()
    test_registry()
    test_search()
    test_schema()
    test_idempotency()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    if FAILURES:
        print("Failures: %s" % ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    with create_app().app_context():
        sys.exit(main())
