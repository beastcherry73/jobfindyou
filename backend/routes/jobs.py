import json
import logging
import os
from flask import Blueprint, request, jsonify, session, render_template

from backend.database import get_db
from backend.decorators import login_required
from backend.services.adzuna_service import (
    list_categories, AdzunaError, AdzunaValidationError, adzuna_configured,
)
from backend.services.jobsources import (
    unified_search, get_countries, any_source_configured,
)
from backend.services import ats, digest
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
    # Job Search now lives inside the workspace shell as an SPA section, so it
    # shares the persistent sidebar with Dashboard/Tracker. This URL deep-links
    # straight to that section.
    return render_template(
        "workspace.html",
        user_name=session.get("user_name", "there"),
        initial_section="jobsearch",
    )


@jobs_bp.route("/app/tracker")
@login_required
def tracker_page():
    # The tracker is a section of the workspace shell now, not a standalone
    # page. This URL is kept because it is bookmarked and linked from older
    # emails; it deep-links straight into the Pipeline tab instead of loading a
    # second, separate app. templates/tracker.html is retained only until those
    # links are confirmed dead.
    return render_template(
        "workspace.html",
        user_name=session.get("user_name", "there"),
        initial_section="pipeline",
    )


# ── Job search (Adzuna proxy) ──────────────────────────────────────────
@jobs_bp.route("/api/jobs/search", methods=["GET"])
@login_required
@rate_limit(limit=30, window_seconds=300)
def api_jobs_search():
    if not any_source_configured():
        return jsonify({"error": "Job search isn't configured yet.", "configured": False}), 503

    args = request.args
    job_type = (args.get("job_type") or "").strip().lower() or None
    try:
        # unified_search routes by country: Adzuna (full filters) where it
        # serves that country, else the global aggregators. Adzuna-specific
        # filters below are applied on the Adzuna path and ignored elsewhere.
        data = unified_search(
            what=(args.get("what") or "").strip(),
            what_exclude=(args.get("what_exclude") or "").strip() or None,
            where=(args.get("where") or "").strip(),
            country=(args.get("country") or "in"),
            page=args.get("page", 1),
            distance=args.get("distance"),
            salary_min=args.get("salary_min"),
            salary_max=args.get("salary_max"),
            salary_include_unknown=args.get("salary_include_unknown"),
            job_type=job_type,
            category=(args.get("category") or "").strip() or None,
            sort_by=(args.get("sort_by") or "").strip() or None,
            max_days_old=args.get("max_days_old"),
            # Exact against the keyless ATS corpus (our own data); ignored by
            # the aggregators, which have no equivalent filter.
            work_mode=(args.get("work_mode") or "").strip().lower(),
            experience_level=(args.get("experience_level") or "").strip().lower(),
        )
        return jsonify(data)
    except AdzunaValidationError as e:
        # Bad/conflicting user filters — 400, with a clear message, never a
        # silent empty result set.
        return jsonify({"error": str(e)}), 400
    except AdzunaError as e:
        return jsonify({"error": str(e)}), 502


@jobs_bp.route("/api/jobs/countries", methods=["GET"])
@login_required
def api_jobs_countries():
    # Static list (no upstream call) — the UI populates its country dropdown and
    # learns which countries are Adzuna markets (so it only shows category
    # filters where they apply).
    return jsonify({"countries": get_countries()})


@jobs_bp.route("/api/jobs/categories", methods=["GET"])
@login_required
@rate_limit(limit=60, window_seconds=300)
def api_jobs_categories():
    if not adzuna_configured():
        return jsonify({"error": "Job search isn't configured yet.", "configured": False}), 503
    try:
        return jsonify({"categories": list_categories(request.args.get("country", "in"))})
    except AdzunaError as e:
        return jsonify({"error": str(e)}), 502


# ── Keyless ATS layer: daily sync + corpus visibility ──────────────────
# Triggered by the Vercel cron entry in vercel.json. Vercel sends
# `Authorization: Bearer $CRON_SECRET` when CRON_SECRET is configured; we
# require it, so this is never an open endpoint. Without CRON_SECRET set the
# route refuses outright rather than running unauthenticated.
@jobs_bp.route("/api/jobs/ats/sync", methods=["GET", "POST"])
def api_ats_sync():
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        return jsonify({"error": "Sync is not configured."}), 503
    provided = request.headers.get("Authorization", "")
    if provided != f"Bearer {secret}":
        return jsonify({"error": "Not authorized."}), 401

    # Bounded so the function returns inside its wall-clock ceiling; the cursor
    # is persisted per company, so the next run resumes rather than restarting.
    try:
        budget = float(request.args.get("budget", 50))
    except (TypeError, ValueError):
        budget = 50.0
    try:
        return jsonify(ats.run_sync(time_budget=budget))
    except Exception as e:
        logger.error(f"ATS sync failed: {e}")
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/ats/status", methods=["GET"])
@login_required
def api_ats_status():
    """What the keyless layer currently holds — registry size and live corpus."""
    return jsonify({"registry": ats.registry_stats(), "corpus": ats.corpus_stats()})


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
        parsed = json.loads(clean_json(
            call_groq(prompt, max_tokens=1500, json_mode=True)))
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


# ── For You: resume-matched shortlist (stage 1 only) ───────────────────
#
# Deliberately does NO AI work. The digest engine's stage 2 scores each
# candidate with a separate Groq call, and ten of those in one request would
# blow the serverless time budget. Instead this returns the keyword shortlist
# fast and the UI fills in match percentages per card through the existing
# /api/jobs/match route - the same lazy pattern Browse already uses.
#
# The `with get_db()` block covers ONLY the two queries. Scoring runs after it
# closes, because the shared connection lock is held for the whole block (see
# CLAUDE.md) and scoring needs no database.

@jobs_bp.route("/api/digest", methods=["GET"])
@login_required
@rate_limit(limit=20, window_seconds=300)
def api_digest():
    args = request.args
    country = (args.get("country") or "").strip().lower()
    try:
        limit = max(1, min(30, int(args.get("limit", digest.DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = digest.DEFAULT_LIMIT
    try:
        max_days_old = max(1, min(365, int(args.get("max_days_old",
                                                    digest.DEFAULT_MAX_DAYS_OLD))))
    except (TypeError, ValueError):
        max_days_old = digest.DEFAULT_MAX_DAYS_OLD

    try:
        with get_db() as db:
            keywords = digest.latest_keywords(db, session["user_id"])
            rows = digest.recall(
                db, [n for _, n in keywords],
                max_days_old=max_days_old, country=country,
            ) if keywords else []
    except Exception as e:
        logger.warning(f"Digest query failed: {e}")
        return jsonify({"error": "Could not build your shortlist just now."}), 502

    # No analysis yet is a normal state for a new account, not an error: the
    # UI needs to tell them to analyze a resume, so it is flagged rather than
    # returned as an empty shortlist that would look like "nothing matched".
    if not keywords:
        return jsonify({
            "keywords": [], "candidates": [], "count": 0,
            "no_resume": True,
        })

    candidates = digest.score_rows(rows, keywords, limit=limit)
    return jsonify({
        "keywords": [d for d, _ in keywords],
        "candidates": candidates,
        "count": len(candidates),
        "no_resume": False,
    })


# ── Apply → seed a 'Viewed' tracker row ────────────────────────────────
# A click on Apply only opens the third-party listing; it is NOT an
# application. We record it as 'Viewed' and let the user self-report the
# actual application later (return-to-tab prompt, or "Mark as Applied" in the
# tracker). JobSpike never inspects the opened tab or the third-party site.

@jobs_bp.route("/api/jobs/description", methods=["GET"])
@login_required
@rate_limit(limit=90, window_seconds=300)
def api_job_description():
    """Full description for one stored job, fetched live when we lack it.

    SmartRecruiters and Breezy publish no description in the list response the
    sync reads, so ~15% of the corpus is stored with an empty body. The detail
    panel calls this when it opens such a role.

    Always 200 with a `description` string -- an empty one simply means the
    employer published none. A missing description must never surface as an
    error state on an otherwise valid listing.
    """
    try:
        text = ats.fetch_full_description(request.args.get("id"))
    except Exception as e:
        logger.warning(f"Description fetch failed: {e}")
        text = ""
    return jsonify({"description": text})

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
