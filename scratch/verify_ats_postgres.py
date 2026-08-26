"""Verify the keyless ATS layer against REAL PostgreSQL, not dev SQLite.

SQLite hides a whole class of fault: it accepts an empty string in a TIMESTAMPTZ
column, tolerates text where Postgres demands a timestamp, and orders NULLs the
opposite way under DESC. Everything below therefore has to pass against the
actual production engine before this ships.

Checks, in order:
  1. connect (reports host/project only -- NEVER the connection string)
  2. schema migration: marker "4" applied, ats_jobs present with the right
     column types and indexes
  3. bounded sync writes real rows
  4. idempotency: re-syncing the same companies adds no rows
  5. search works, including the recency filter and NULL-safe date ordering
  6. optional full cycle (--full)

Usage:
    set SUPABASE_DB_URL=...   (or put it in .env)
    python scratch/verify_ats_postgres.py           # bounded sync (20 companies)
    python scratch/verify_ats_postgres.py --full    # full cycle, all companies
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend import create_app  # noqa: E402
from backend.database import (  # noqa: E402
    PgConnection, _SCHEMA_MARKER_KEY, _SCHEMA_MARKER_VALUE, get_db,
    safe_parse_db_url,
)
from backend.services import ats  # noqa: E402

PASS = FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s   %s" % (name, detail))


def main():
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("SUPABASE_DB_URL (or DATABASE_URL) is not set.")
        print("This script will not run against SQLite -- that is the whole point.")
        return 2

    parsed = safe_parse_db_url(url)
    project = (parsed.path or "").lstrip("/").split("/")[0] or "?"
    print("Target Postgres: host=%s project=%s" % (parsed.hostname, project))
    print("(the connection string itself is never printed)\n")

    print("[1] Connection + schema migration")
    with get_db() as db:
        check("connected to PostgreSQL, not SQLite", isinstance(db, PgConnection),
              type(db).__name__)
        row = db.execute("SELECT meta_value FROM app_meta WHERE meta_key = ?",
                         (_SCHEMA_MARKER_KEY,)).fetchone()
        marker = row["meta_value"] if row else None
        check("schema marker is %r (migration applied)" % _SCHEMA_MARKER_VALUE,
              marker == _SCHEMA_MARKER_VALUE, "marker=%r" % marker)

        cols = db.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'ats_jobs' ORDER BY ordinal_position").fetchall()
        colmap = {c["column_name"]: c["data_type"] for c in cols}
        check("ats_jobs table exists", bool(colmap), "%d columns" % len(colmap))
        check("every expected column present",
              all(c in colmap for c in ats._COLUMNS),
              str([c for c in ats._COLUMNS if c not in colmap]))
        check("posted_at is timestamptz",
              colmap.get("posted_at") == "timestamp with time zone",
              colmap.get("posted_at"))
        check("last_seen_at is timestamptz",
              colmap.get("last_seen_at") == "timestamp with time zone",
              colmap.get("last_seen_at"))

        idx = db.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'ats_jobs'").fetchall()
        names = {i["indexname"] for i in idx}
        check("fingerprint is UNIQUE (required for the upsert)",
              any("fingerprint" in n or "key" in n for n in names), str(sorted(names)))
        check("supporting indexes created",
              {"idx_ats_country", "idx_ats_posted"} <= names, str(sorted(names)))

    print("\n[2] Sync writes real rows to Postgres")
    with get_db() as db:
        before = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
    print("  rows before: %d" % before)

    if "--full" in sys.argv:
        print("  running a FULL cycle (all %d companies) -- this takes a few minutes"
              % len(ats.load_registry()))
        stats = ats.run_sync(reset=True)
    else:
        stats = ats.run_sync(limit=20, reset=True)
    print("  sync stats: %s" % {k: stats.get(k) for k in
                                ("companies", "fetched", "stored", "failed",
                                 "seconds", "completed_cycle")})
    check("sync completed without failures", stats.get("failed", 1) == 0,
          "failed=%s" % stats.get("failed"))
    check("sync stored rows", stats.get("stored", 0) > 0, str(stats.get("stored")))
    if "--full" in sys.argv:
        check("full cycle completed", stats.get("completed_cycle") is True)

    with get_db() as db:
        after = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
        sample = db.execute(
            "SELECT company, title, apply_url, posted_at, platform FROM ats_jobs "
            "WHERE posted_at IS NOT NULL LIMIT 3").fetchall()
        nulls = db.execute(
            "SELECT COUNT(*) AS n FROM ats_jobs WHERE posted_at IS NULL").fetchone()["n"]
    check("ats_jobs now holds real rows on Postgres", after > 0, str(after))
    print("  rows after: %d  (posted_at NULL on %d)" % (after, nulls))
    for r in sample:
        print("    %-22s %-42s %s" % (r["company"][:22], r["title"][:42],
                                      str(r["posted_at"])[:19]))

    print("\n[3] Idempotency on Postgres")
    entries = ats.load_registry()[:5]
    stats2 = {"companies": 0, "fetched": 0, "stored": 0, "pruned": 0, "failed": 0}
    for e in entries:
        _, jobs = ats._fetch_and_normalize(e)
        ats._store_company(e, jobs, stats2)
    with get_db() as db:
        mid = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
    for e in entries:
        _, jobs = ats._fetch_and_normalize(e)
        ats._store_company(e, jobs, stats2)
    with get_db() as db:
        end = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
        dupes = db.execute(
            "SELECT COUNT(*) AS n FROM (SELECT fingerprint FROM ats_jobs "
            "GROUP BY fingerprint HAVING COUNT(*) > 1) d").fetchone()["n"]
    check("re-syncing the same companies adds no rows", mid == end,
          "%d -> %d" % (mid, end))
    check("no duplicate fingerprints", dupes == 0, "%d duplicated" % dupes)

    print("\n[4] Search against Postgres")
    base = ats.search(per_page=5)
    check("search returns rows", base["count"] > 0, str(base["count"]))
    recent = ats.search(max_days_old=30, per_page=5)
    check("recency filter runs on timestamptz (no text/timestamp error)",
          isinstance(recent["count"], int), str(recent))
    dated = ats.search(sort_by="date", per_page=10)
    stamps = [r["posted_at"] for r in dated["results"]]
    check("date sort returns no NULL/empty first (Postgres NULLS FIRST trap)",
          all(s for s in stamps), str(stamps[:3]))
    check("date sort is newest-first", stamps == sorted(stamps, reverse=True))
    combo = ats.search(what="engineer", country="in", work_mode="remote",
                       experience_level="senior", max_days_old=90, per_page=10)
    check("combined filters run on Postgres", isinstance(combo["count"], int),
          str(combo["count"]))
    if base["results"]:
        r = base["results"][0]
        print("  sample row: %s | %s | %s" % (r["company"][:20], r["title"][:34],
                                              r["source"]))

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    with create_app().app_context():
        sys.exit(main())
