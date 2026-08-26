"""Run the keyless-ATS job sync from the command line.

The same code path the daily cron uses (backend.services.ats.run_sync), exposed
for local full syncs and for verifying idempotency by re-running it.

Usage:
    python scratch/sync_ats_jobs.py                 # resume from the cursor, full pass
    python scratch/sync_ats_jobs.py --limit 20      # only 20 companies
    python scratch/sync_ats_jobs.py --budget 60     # stop after 60 seconds
    python scratch/sync_ats_jobs.py --reset         # start again from the top
    python scratch/sync_ats_jobs.py --stats         # just report the corpus
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app  # noqa: E402
from backend.services.ats import corpus_stats, registry_stats, run_sync  # noqa: E402


def arg(flag, cast=int, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            try:
                return cast(sys.argv[i + 1])
            except ValueError:
                return default
    return default


def main():
    print("Registry: %s" % registry_stats())
    if "--stats" in sys.argv:
        print("Corpus  : %s" % corpus_stats())
        return

    stats = run_sync(limit=arg("--limit"), time_budget=arg("--budget", float),
                     reset="--reset" in sys.argv)
    print("\nSync result:")
    for k in ("companies", "fetched", "stored", "pruned", "failed", "seconds",
              "cursor", "registry_size", "completed_cycle", "pruned_unregistered",
              "pruned_stale", "error"):
        if k in stats:
            print("  %-16s %s" % (k, stats[k]))
    print("\nCorpus  : %s" % corpus_stats())


if __name__ == "__main__":
    # The dev SQLite path resolves its file from app.config, so the CLI runs
    # inside a real app context. The production Postgres path reads env only.
    with create_app().app_context():
        main()
