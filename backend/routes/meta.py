from flask import Blueprint, jsonify
from backend.database import db_diagnostic, get_db

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/api/_tmp/db_probe")
def db_probe():
    """TEMPORARY diagnostic (remove after investigation). Never serve secrets."""
    import time

    out = {}
    try:
        with get_db() as db:
            t0 = time.time()
            db.execute("SELECT 1").fetchall()
            out["select1_ms"] = round((time.time() - t0) * 1000)

            t0 = time.time()
            rows = db.execute(
                "SELECT id FROM analyses ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            out["analyses_sample_ms"] = round((time.time() - t0) * 1000)
            out["analyses_sample_rows"] = len(rows)

            t0 = time.time()
            counts = db.execute(
                """SELECT relname, n_live_tup FROM pg_stat_user_tables
                   WHERE relname IN ('analyses','resumes','users') ORDER BY relname"""
            ).fetchall()
            out["table_counts_ms"] = round((time.time() - t0) * 1000)
            out["table_counts"] = {r["relname"]: int(r["n_live_tup"]) for r in counts}
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return jsonify(out)


@meta_bp.route("/api/health/db")
def db_health():
    """Safe database diagnostic endpoint.

    Reports only:
    - database backend (PostgreSQL / SQLite)
    - whether the required DB env var exists (boolean, NOT the value)
    - database host / project identifier derived from the URL (no credentials)
    """
    return jsonify(db_diagnostic())


@meta_bp.route("/api/health")
def health():
    return jsonify({"status": "ok"})