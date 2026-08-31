"""Verify the For You digest request path against REAL PostgreSQL, not SQLite.

The digest's stage-1 request path (`digest.recall` + `digest.score_rows`, behind
GET /api/digest) is READ-only and adds no schema, but its SQL leans on several
things dev SQLite will happily accept and production Postgres may not:

  * `LIKE ? ESCAPE '\'` -- the escape literal must survive
    standard_conforming_strings.
  * a `CASE WHEN <n LIKE terms> THEN 0 ELSE 1 END` sort tier, evaluated over
    the whole eligible set.
  * `posted_at >= ?` on a TIMESTAMPTZ column, where pg8000 sends a Python str
    as OID 25 (TEXT) and Postgres refuses the comparison. `_timestamp_param`
    exists for exactly this and must be exercised on the real engine.
  * `ORDER BY (posted_at IS NULL), posted_at DESC` -- Postgres sorts NULLs
    FIRST under DESC, SQLite last, so a "newest first" list silently leads
    with undated rows in production if the guard is dropped.
  * up to ~3x keywords bound parameters in one statement.

And the measurement that matters most and CANNOT be inferred from SQLite: how
long `recall` holds the SHARED connection lock on the real pooler. The whole
reason this path exists is that the batch path held it for 13-23s; if Postgres
is no better, that is a finding, not a detail.

Usage:
    set SUPABASE_DB_URL=...   (or put it in .env)
    python scratch/verify_digest_postgres.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend import create_app  # noqa: E402
from backend.database import PgConnection, get_db, safe_parse_db_url  # noqa: E402
from backend.services import digest  # noqa: E402

PASS = FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
    return bool(condition)


def main():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set. This check is meaningless against "
              "SQLite -- see the module docstring.")
        return 2

    # Host/project only. Never print the connection string.
    parsed = safe_parse_db_url(url)
    print(f"\n[1] Connection\n  host={parsed.hostname} db={(parsed.path or '').lstrip('/')}")

    app = create_app()
    with app.app_context():
        with get_db() as db:
            is_pg = isinstance(db, PgConnection)
            check("connected to PostgreSQL (not SQLite)", is_pg,
                  type(db).__name__)
            if not is_pg:
                return 1
            total = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()["n"]
            print(f"  corpus: {total} rows")

        print("\n[2] Users with analyses")
        with get_db() as db:
            rows = db.execute(
                "SELECT DISTINCT user_id FROM analyses WHERE user_id IS NOT NULL"
            ).fetchall()
        uids = [r["user_id"] for r in rows]
        check("at least one user has an analysis to match against", bool(uids),
              f"{len(uids)} user(s)")
        if not uids:
            return 1

        tested = 0
        for uid in uids:
            with get_db() as db:
                kws = digest.latest_keywords(db, uid)
            if not kws:
                continue
            tested += 1
            print(f"\n[3] user {uid} -- {len(kws)} keywords: "
                  f"{[d for d, _ in kws][:6]}")

            # --- the dialect surface, on the real engine -------------------
            with get_db() as db:
                t0 = time.perf_counter()
                try:
                    recalled = digest.recall(db, [n for _, n in kws])
                    err = None
                except Exception as e:                      # noqa: BLE001
                    recalled, err = [], e
                t_lock = time.perf_counter() - t0
            if not check(f"recall() executes on Postgres (user {uid})", err is None,
                         str(err) if err else f"{len(recalled)} rows"):
                continue

            # The measurement this script exists for.
            check(f"recall() holds the shared lock under 2.5s (user {uid})",
                  t_lock < 2.5, f"{t_lock * 1000:.0f} ms")

            # NULL-safe ordering. Postgres puts NULLs FIRST under a bare DESC,
            # so without the `(posted_at IS NULL)` guard the list would lead
            # with undated rows in production while looking correct on SQLite.
            leads_with_undated = bool(recalled) \
                and recalled[0]["posted_at"] is None \
                and any(r["posted_at"] is not None for r in recalled)
            check(f"undated rows do not lead the ordering (user {uid})",
                  not leads_with_undated)

            t0 = time.perf_counter()
            scored = digest.score_rows(recalled, kws)
            t_score = time.perf_counter() - t0
            check(f"score_rows() returns candidates (user {uid})", bool(scored),
                  f"{len(scored)} candidates in {t_score * 1000:.0f} ms (no lock)")

            if scored:
                c = scored[0]
                check(f"candidate carries the unified job schema (user {uid})",
                      all(k in c for k in ("title", "company", "redirect_url",
                                           "company_logo", "apply_is_direct",
                                           "match_score", "matched_keywords")),
                      f"top: {str(c.get('title'))[:44]!r} score={c.get('match_score')}")
                # to_unified must normalize the Postgres datetime to a string,
                # or jsonify would fail / vary by engine.
                check(f"posted_at serialized as a string (user {uid})",
                      isinstance(c.get("posted_at"), str),
                      f"{type(c.get('posted_at')).__name__}={c.get('posted_at')!r}")

            # --- parity against the batch path -----------------------------
            with get_db() as db:
                idx = digest.build_index(db, [n for _, n in kws])
            batch = digest.rank(idx, kws)
            new_k = {(j["title"], j["company"]) for j in scored}
            old_k = {(j["title"], j["company"]) for j in batch}
            overlap = len(new_k & old_k)
            # Divergence is expected and documented when the cap truncates; it
            # must sit in the description-only tail, never lose everything.
            check(f"request path overlaps the batch path (user {uid})",
                  overlap >= max(1, min(len(old_k), len(new_k)) // 2),
                  f"{overlap}/{len(old_k)} shared")

        check("at least one user actually exercised the path", tested > 0,
              f"{tested} user(s)")

        # --- the route itself, over the real engine ------------------------
        print("\n[4] GET /api/digest end to end")
        app.config["TESTING"] = True
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["user_id"] = uids[0]
            t0 = time.perf_counter()
            res = c.get("/api/digest")
            dt = time.perf_counter() - t0
        check("route returns 200", res.status_code == 200,
              f"{res.status_code} in {dt * 1000:.0f} ms")
        data = res.get_json() or {}
        check("response is JSON-serializable with the expected keys",
              all(k in data for k in ("keywords", "candidates", "count")),
              f"count={data.get('count')}")

    print("\n" + "=" * 50)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 50)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
