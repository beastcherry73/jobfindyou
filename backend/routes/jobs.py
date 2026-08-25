import json
import logging
from flask import Blueprint, request, jsonify, session, render_template

from backend.database import get_db
from backend.decorators import login_required
from backend.services.adzuna_service import (
    search_jobs, list_categories, AdzunaError, AdzunaValidationError,
    adzuna_configured,
)
from backend.services.ai import call_groq, GroqError
from backend.services.helpers import clean_json
from backend.prompts import JOB_MATCH_PROMPT
from backend.services.ratelimit import rate_limit

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)


# ── Pages ──────────────────────────────────────────────────────────────
@jobs_bp.route("/app/jobs")
@login_required
def jobs_page():
    return render_template("jobs.html", user_name=session.get("user_name", "there"))


@jobs_bp.route("/app/tracker")
@login_required
def tracker_page():
    return render_template("tracker.html", user_name=session.get("user_name", "there"))


# ── Job search (Adzuna proxy) ──────────────────────────────────────────
@jobs_bp.route("/api/jobs/search", methods=["GET"])
@login_required
@rate_limit(limit=30, window_seconds=300)
def api_jobs_search():
    if not adzuna_configured():
        return jsonify({"error": "Job search isn't configured yet.", "configured": False}), 503

    args = request.args
    job_type = (args.get("job_type") or "").strip().lower() or None
    try:
        data = search_jobs(
            what=(args.get("what") or "").strip(),
            where=(args.get("where") or "").strip(),
            page=args.get("page", 1),
            distance=args.get("distance"),
            salary_min=args.get("salary_min"),
            salary_max=args.get("salary_max"),
            salary_include_unknown=args.get("salary_include_unknown"),
            job_type=job_type,
            category=(args.get("category") or "").strip() or None,
            sort_by=(args.get("sort_by") or "").strip() or None,
            max_days_old=args.get("max_days_old"),
        )
        return jsonify(data)
    except AdzunaValidationError as e:
        # Bad/conflicting user filters — 400, with a clear message, never a
        # silent empty result set.
        return jsonify({"error": str(e)}), 400
    except AdzunaError as e:
        return jsonify({"error": str(e)}), 502


@jobs_bp.route("/api/jobs/categories", methods=["GET"])
@login_required
@rate_limit(limit=60, window_seconds=300)
def api_jobs_categories():
    if not adzuna_configured():
        return jsonify({"error": "Job search isn't configured yet.", "configured": False}), 503
    try:
        return jsonify({"categories": list_categories()})
    except AdzunaError as e:
        return jsonify({"error": str(e)}), 502


def _latest_resume_text(user_id, analysis_id=None):
    """Pull raw resume text for the user — a specific analysis if given,
    else their most recent. Returns '' if none found."""
    with get_db() as db:
        if analysis_id:
            row = db.execute(
                "SELECT full_json FROM analyses WHERE id = ? AND user_id = ?",
                (analysis_id, user_id),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT full_json FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
    if not row or not row["full_json"]:
        return ""
    try:
        fj = json.loads(row["full_json"]) if isinstance(row["full_json"], str) else row["full_json"]
        return (fj.get("raw_text") or fj.get("rawText") or "").strip()
    except Exception:
        return ""


# ── Per-listing Job Match (lazy: one call per card, on demand) ─────────
@jobs_bp.route("/api/jobs/match", methods=["POST"])
@login_required
@rate_limit(limit=40, window_seconds=300)
def api_jobs_match():
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"error": "No job description to match against."}), 400

    resume_text = _latest_resume_text(session["user_id"], body.get("analysis_id"))
    if not resume_text:
        return jsonify({
            "error": "Analyze a resume first so we have something to match against.",
            "no_resume": True,
        }), 400

    try:
        prompt = JOB_MATCH_PROMPT.format(
            job_description=description[:4000],
            resume_text=resume_text[:12000],
        )
        parsed = json.loads(clean_json(call_groq(prompt, max_tokens=1500)))
    except GroqError:
        return jsonify({"error": "AI is temporarily unavailable. Try again shortly."}), 502
    except Exception as e:
        logger.warning(f"Job match parse failed: {e}")
        return jsonify({"error": "Could not compute a match for this listing."}), 502

    if not isinstance(parsed, dict) or "match_percent" not in parsed:
        return jsonify({"error": "Could not compute a match for this listing."}), 502

    try:
        match_percent = max(0, min(100, int(parsed.get("match_percent", 0))))
    except (ValueError, TypeError):
        match_percent = 0
    mk = parsed.get("matching_keywords")
    xk = parsed.get("missing_keywords")
    return jsonify({
        "match_percent": match_percent,
        "matching_keywords": mk if isinstance(mk, list) else [],
        "missing_keywords": xk if isinstance(xk, list) else [],
    })


# ── Apply → seed a 'Viewed' tracker row ────────────────────────────────
# A click on Apply only opens the third-party listing; it is NOT an
# application. We record it as 'Viewed' and let the user self-report the
# actual application later (return-to-tab prompt, or "Mark as Applied" in the
# tracker). JobSpike never inspects the opened tab or the third-party site.
@jobs_bp.route("/api/jobs/track", methods=["POST"])
@login_required
def api_jobs_track():
    body = request.get_json(silent=True) or {}
    title = (body.get("job_title") or "").strip()
    if not title:
        return jsonify({"error": "Missing job title."}), 400
    company = (body.get("company") or "").strip()
    location = (body.get("location") or "").strip()
    listing_url = (body.get("listing_url") or "").strip()
    match_percent = body.get("match_percent")
    try:
        match_percent = int(match_percent) if match_percent is not None else None
    except (ValueError, TypeError):
        match_percent = None

    try:
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO jobs_tracker
                   (user_id, job_title, company, location, listing_url, match_percent,
                    status, viewed_date)
                   VALUES (?, ?, ?, ?, ?, ?, 'Viewed', CURRENT_TIMESTAMP)""",
                (session["user_id"], title, company, location, listing_url, match_percent),
            )
            new_id = cursor.lastrowid
        return jsonify({"id": new_id, "status": "Viewed"}), 201
    except Exception as e:
        logger.error(f"Tracker insert failed: {e}")
        return jsonify({"error": "Could not save this listing."}), 500


# ── Tracker list + status update ───────────────────────────────────────
@jobs_bp.route("/api/tracker", methods=["GET"])
@login_required
def api_tracker_list():
    try:
        with get_db() as db:
            rows = db.execute(
                """SELECT id, job_title, company, location, listing_url, match_percent,
                          status, viewed_date, applied_date FROM jobs_tracker
                   WHERE user_id = ?
                   ORDER BY COALESCE(applied_date, viewed_date) DESC""",
                (session["user_id"],),
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_VALID_STATUSES = {"Applied", "Interview", "Offer", "Rejected"}


@jobs_bp.route("/api/tracker/<int:row_id>", methods=["PATCH", "DELETE"])
@login_required
def api_tracker_update(row_id):
    user_id = session["user_id"]
    if request.method == "DELETE":
        try:
            with get_db() as db:
                db.execute("DELETE FROM jobs_tracker WHERE id = ? AND user_id = ?", (row_id, user_id))
            return jsonify({"deleted": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").strip()
    if status not in _VALID_STATUSES:
        return jsonify({"error": "Invalid status."}), 400
    try:
        with get_db() as db:
            if status == "Applied":
                # Self-reported application (confirmation prompt or the tracker's
                # "Mark as Applied"): stamp applied_date now so it reflects the
                # real moment, not the earlier 'Viewed' placeholder.
                db.execute(
                    "UPDATE jobs_tracker SET status = ?, applied_date = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    (status, row_id, user_id),
                )
            else:
                db.execute(
                    "UPDATE jobs_tracker SET status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (status, row_id, user_id),
                )
        return jsonify({"id": row_id, "status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
