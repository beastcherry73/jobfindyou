import json
import hashlib
import statistics
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify, session
from backend.database import get_db
from backend.decorators import login_required
from backend.services.helpers import extract_text_from_pdf, clean_json, normalize_analysis_dict
from backend.services import ai
from backend.services.ai import call_groq, GroqError
from backend.services.ratelimit import rate_limit
from backend.prompts import ANALYSIS_PROMPT, JOB_MATCH_PROMPT, REFERENCE_STANDARD
import logging

logger = logging.getLogger(__name__)

analysis_bp = Blueprint("analysis", __name__)

# 4500, not 6000. Measured 2026-09-11 on the real prompt: completions ran
# 1,132-3,161 tokens, so 4500 is ample - and prompt (~2,800) + 6000 exceeded
# gpt-oss's entire 8,000 TPM bucket, which made the router skip the best
# models for every analysis (see the table in backend/services/ai.py).
ANALYSIS_MAX_TOKENS = 4500
# How long to wait for the concurrent job-match call once the analysis itself
# is done. It normally finishes first (0.8-4s vs 2-8s); this only bounds the
# failover case so a slow match can never hold the whole response hostage.
_MATCH_WAIT_SECONDS = 20

# ── "Analyses are slow right now" ──────────────────────────────────────────
# How long real, completed analyses have actually been taking on THIS
# instance. In memory and per instance on purpose: Vercel runs several, and a
# database write per analysis would add contention to the shared connection
# for what is only a UI hint.
#
# Normal was measured at 2.3-2.8s (gpt-oss-20b) and 7.4s (gpt-oss-120b) on
# 2026-09-11. 14s means the fast models are unavailable and something slower
# is serving, which is the case worth warning about. Three samples minimum,
# so one cold start cannot trip it.
_RECENT_MAX = 8
_MIN_SAMPLES = 3
SLOW_ANALYSIS_SECONDS = 14.0
_recent_seconds = deque(maxlen=_RECENT_MAX)
_recent_lock = threading.Lock()


def _record_analysis_seconds(seconds):
    try:
        with _recent_lock:
            _recent_seconds.append(float(seconds))
    except (TypeError, ValueError):
        pass


def recent_analysis_median():
    """(median_seconds, sample_count), or (None, n) below the sample floor."""
    with _recent_lock:
        samples = list(_recent_seconds)
    if len(samples) < _MIN_SAMPLES:
        return None, len(samples)
    return statistics.median(samples), len(samples)


def reset_recent_analysis_times():
    """Test hook: forget the measured samples."""
    with _recent_lock:
        _recent_seconds.clear()


def _is_substantive(d):
    """True when a parsed analysis actually contains an analysis.

    Some models return VALID JSON with none of the content - no score, no
    dimensions (groq/compound-mini and gemini-flash-lite-latest both did on
    the real prompt, 2026-09-11). normalize_analysis_dict would then pad that
    with a default score of 75 and canned verdict text, and the user would get
    a plausible-looking report nobody wrote. Reject it and retry elsewhere.
    """
    if not isinstance(d, dict) or not d:
        return False
    try:
        score = float(d.get("overall_score"))
    except (TypeError, ValueError):
        return False
    if not 0 <= score <= 100:
        return False
    dims = d.get("dimension_scores")
    if not isinstance(dims, dict):
        return False
    numeric = 0
    for v in dims.values():
        try:
            float(v)
            numeric += 1
        except (TypeError, ValueError):
            pass
    if numeric < 4:
        return False
    # At least one real finding. The hollow responses had none of anything; a
    # genuine report on a strong resume can legitimately list very few.
    findings = sum(len(d.get(k)) for k in ("strengths", "weaknesses", "suggestions")
                   if isinstance(d.get(k), list))
    return findings >= 1


def _run_analysis(prompt):
    """Up to two attempts; the second never reuses the model that failed.

    Returns (parsed, failure) where failure is None, "unavailable" (every
    model refused) or "empty" (nothing usable came back twice).
    """
    tried = set()
    for attempt in (1, 2):
        try:
            with ai.excluding(tried):
                raw = clean_json(call_groq(prompt, max_tokens=ANALYSIS_MAX_TOKENS,
                                           json_mode=True))
        except GroqError:
            return None, "unavailable"
        served = ai.last_model()
        if served:
            tried.add(served)
        try:
            candidate = json.loads(raw)
        except Exception:
            candidate = None
        # A non-resume verdict is a real answer, not a quality failure.
        if isinstance(candidate, dict) and candidate.get("is_resume") is False:
            return candidate, None
        if _is_substantive(candidate):
            return candidate, None
        # Log the head of what actually came back: without it the next person
        # debugging this has nothing but the 502 to go on.
        logger.warning(
            "Analysis unusable on attempt %s/2 (model %s); response head: %r",
            attempt, served, (raw or "")[:200])
    return None, "empty"


def _compute_job_match(job_description, resume_text):
    """The job-match call. Returns the job_match dict, or None."""
    match_prompt = JOB_MATCH_PROMPT.format(
        job_description=job_description[:4000],
        resume_text=resume_text[:12000],
    )
    # 2500, not 1500: measured 2026-08-29, groq/compound-mini spends 1725
    # completion tokens on this prompt and so was truncated mid-object at the
    # old budget, which silently dropped job_match from the response.
    match_raw = clean_json(call_groq(match_prompt, max_tokens=2500, json_mode=True))
    match_parsed = json.loads(match_raw)
    if not (isinstance(match_parsed, dict) and "match_percent" in match_parsed):
        return None
    try:
        match_percent = max(0, min(100, int(match_parsed.get("match_percent", 0))))
    except (ValueError, TypeError):
        match_percent = 0
    matching_keywords = match_parsed.get("matching_keywords")
    missing_keywords = match_parsed.get("missing_keywords")
    raw_gaps = match_parsed.get("skill_gaps")
    skill_gaps = []
    if isinstance(raw_gaps, list):
        for g in raw_gaps[:5]:
            if isinstance(g, dict) and g.get("skill"):
                skill_gaps.append({
                    "skill": str(g.get("skill", "")).strip(),
                    "why_it_matters": str(g.get("why_it_matters", "")).strip(),
                    "how_to_address": str(g.get("how_to_address", "")).strip(),
                })
    return {
        "match_percent": match_percent,
        "matching_keywords": matching_keywords if isinstance(matching_keywords, list) else [],
        "missing_keywords": missing_keywords if isinstance(missing_keywords, list) else [],
        "gap_summary": str(match_parsed.get("gap_summary", "")).strip(),
        "skill_gaps": skill_gaps,
    }


@analysis_bp.route("/api/analyze/load", methods=["GET"])
def analyze_load():
    """Whether analyses are genuinely running slow right now.

    Two measured signals, no probability and no claim about how many people
    are using the site:

      * the AI pool -- how many of the models that could serve an analysis
        are in back-off or out of OBSERVED token headroom (Groq reports
        remaining quota in its own response headers). Every one of them
        unavailable means the next analysis waits on a reset or a slower
        fallback;
      * measured latency -- the median of the last few completed analyses on
        this instance, against a threshold taken from real timings.

    Unknown is NOT high load. With nothing configured, nothing observed, or
    anything raising, the answer is false and the UI shows nothing, which is
    exactly the behaviour before this endpoint existed.
    """
    high, reason = False, None
    measured = {}

    try:
        pool = ai.pool_status(ANALYSIS_MAX_TOKENS, json_mode=True)
        measured["models_eligible"] = pool["eligible"]
        measured["models_ready"] = pool["ready"]
        # Two or more, so a single-model configuration (a dev box with one
        # key) is never reported as saturated.
        if pool["eligible"] >= 2 and pool["ready"] == 0:
            high, reason = True, "ai_capacity"
    except Exception:
        logger.warning("Load check: AI pool status unavailable", exc_info=True)

    try:
        median, samples = recent_analysis_median()
        measured["samples"] = samples
        if median is not None:
            measured["recent_median_seconds"] = round(median, 1)
            if median >= SLOW_ANALYSIS_SECONDS:
                high, reason = True, "slow_recent"
    except Exception:
        logger.warning("Load check: latency samples unavailable", exc_info=True)

    return jsonify({"high_load": high, "reason": reason, "measured": measured})


@analysis_bp.route("/api/analyze", methods=["POST"])
@rate_limit(limit=10, window_seconds=300)
def analyze():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    job_description = request.form.get("job_description", "").strip()

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not file.filename.lower().endswith((".pdf", ".txt")):
        return jsonify({"error": "Please upload a PDF or TXT file"}), 400

    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > 10 * 1024 * 1024:
        return jsonify({"error": "File size exceeds 10 MB limit"}), 400

    started_at = time.perf_counter()
    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        else:
            resume_text = file.read().decode("utf-8", errors="ignore")

        if not resume_text.strip():
            return jsonify({
                "error": "Could not read any text from this file. Scanned or image-based PDFs and empty files are not supported. Please upload a text-based PDF or TXT resume."
            }), 400

        job_context = (
            f"The candidate is applying for this role: {job_description}"
            if job_description
            else "No specific job description provided. Give a general analysis."
        )

        prompt = ANALYSIS_PROMPT.format(
            reference_standard=REFERENCE_STANDARD,
            job_context=job_context,
            resume_text=resume_text[:12000],
        )
        # The job match runs CONCURRENTLY with the analysis. Both read only the
        # resume text and the JD, so running them back to back paid the match
        # call's full latency (0.8-4s measured) on every analysis with a JD.
        match_future = None
        match_pool = None
        if job_description:
            match_pool = ThreadPoolExecutor(max_workers=1)
            match_future = match_pool.submit(_compute_job_match, job_description, resume_text)

        # Two attempts (a bad roll is not a broken model), and the retry never
        # reuses the model that produced the unusable answer. The happy path
        # still costs exactly one call.
        try:
            parsed, failure = _run_analysis(prompt)
        finally:
            if match_pool is not None:
                match_pool.shutdown(wait=False)

        if failure == "unavailable":
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502
        if parsed is None:
            return jsonify({"error": "AI service returned an empty result. Please try again."}), 502

        if parsed.get("is_resume") is False:
            return jsonify({
                "error": "This file doesn't look like a resume. Please upload an actual resume or CV (PDF or TXT)."
            }), 400

        result = normalize_analysis_dict(parsed)
        result["filename"] = file.filename
        result["raw_text"] = resume_text

        if match_future is not None:
            try:
                job_match = match_future.result(timeout=_MATCH_WAIT_SECONDS)
                if job_match:
                    result["job_match"] = job_match
            except Exception as match_err:
                # Job match is a bonus, not core to the analysis — never fail
                # the whole request over it. No job_match key means the UI
                # correctly shows nothing rather than a fabricated number.
                logger.warning(f"Job match computation failed: {match_err}")

        content_hash = hashlib.sha256(resume_text.encode("utf-8", errors="ignore")).hexdigest()

        user_id = session.get("user_id")
        file_path = None
        mime_type = "application/pdf" if file.filename.lower().endswith(".pdf") else "text/plain"

        if user_id:
            try:
                from backend.services.supabase_service import upload_resume_to_storage
                file_path = upload_resume_to_storage(file, user_id, file.filename)
            except Exception as st_err:
                import logging
                logging.getLogger(__name__).warning(f"Storage upload error: {st_err}")

        if user_id:
            try:
                with get_db() as db:
                    existing_analysis = db.execute(
                        "SELECT id FROM analyses WHERE user_id = ? AND content_hash = ?",
                        (user_id, content_hash)
                    ).fetchone()

                    if existing_analysis:
                        analysis_id = existing_analysis["id"]
                        db.execute(
                            """UPDATE analyses SET
                                filename = ?, job_description = ?, overall_score = ?,
                                dimension_scores = ?, summary = ?, strengths = ?,
                                weaknesses = ?, missing_sections = ?, ats_issues = ?,
                                suggestions = ?, suggested_keywords = ?, full_json = ?,
                                file_path = ?, content_hash = ?, created_at = CURRENT_TIMESTAMP
                                WHERE id = ? AND user_id = ?""",
                            (
                                file.filename,
                                job_description,
                                result["overall_score"],
                                json.dumps(result["dimension_scores"]),
                                result["summary"],
                                json.dumps(result["strengths"]),
                                json.dumps(result["weaknesses"]),
                                json.dumps(result["missing_sections"]),
                                json.dumps(result["ats_issues"]),
                                json.dumps(result["suggestions"]),
                                json.dumps(result["suggested_keywords"]),
                                json.dumps(result),
                                file_path,
                                content_hash,
                                analysis_id,
                                user_id
                            )
                        )
                    else:
                        cursor = db.execute(
                            """INSERT INTO analyses (
                                user_id, filename, job_description, overall_score,
                                dimension_scores, summary, strengths, weaknesses,
                                missing_sections, ats_issues, suggestions, suggested_keywords,
                                full_json, file_path, content_hash
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                user_id,
                                file.filename,
                                job_description,
                                result["overall_score"],
                                json.dumps(result["dimension_scores"]),
                                result["summary"],
                                json.dumps(result["strengths"]),
                                json.dumps(result["weaknesses"]),
                                json.dumps(result["missing_sections"]),
                                json.dumps(result["ats_issues"]),
                                json.dumps(result["suggestions"]),
                                json.dumps(result["suggested_keywords"]),
                                json.dumps(result),
                                file_path,
                                content_hash
                            )
                        )
                        analysis_id = cursor.lastrowid
                    result["id"] = analysis_id

                    existing = db.execute(
                        "SELECT id FROM resumes WHERE user_id = ? AND filename = ?",
                        (user_id, file.filename)
                    ).fetchone()

                    data_payload = json.dumps({
                        "fullName": file.filename.rsplit('.', 1)[0],
                        "summary": result.get("summary", ""),
                        "skills": result.get("skills") or ", ".join(result.get("suggested_keywords", [])),
                        "experience": result.get("experience", []),
                        "education": result.get("education", []),
                        "projects": result.get("projects", []),
                        "certifications": result.get("certifications", []),
                        "rawText": resume_text
                    })

                    if existing:
                        db.execute(
                            """UPDATE resumes SET 
                                title = ?, overall_score = ?, analysis_json = ?, data_json = ?, file_path = ?, file_size = ?, mime_type = ?, updated_at = CURRENT_TIMESTAMP 
                                WHERE id = ? AND user_id = ?""",
                            (file.filename, result["overall_score"], json.dumps(result), data_payload, file_path, size, mime_type, existing["id"], user_id)
                        )
                        result["resume_id"] = existing["id"]
                    else:
                        res_cur = db.execute(
                            """INSERT INTO resumes (
                                user_id, title, filename, template, overall_score, analysis_json, data_json, file_path, file_size, mime_type
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (user_id, file.filename, file.filename, 'modern', result["overall_score"], json.dumps(result), data_payload, file_path, size, mime_type)
                        )
                        result["resume_id"] = res_cur.lastrowid
                    db.commit()
            except Exception as db_err:
                # A database failure must NEVER look like a successful save.
                import logging
                logging.getLogger(__name__).error(
                    f"Failed to save analysis to DB for user {user_id}: {db_err}",
                    exc_info=True
                )
                return jsonify({
                    "error": "The analysis completed but could not be saved. Your report may not appear in Previous Analyses. Please try again.",
                    "saved": False
                }), 500

        # Only successful analyses are timed: that is what "how long does an
        # analysis take" means to the person waiting.
        _record_analysis_seconds(time.perf_counter() - started_at)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500


@analysis_bp.route("/api/analyses/claim", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def claim_analysis():
    user_id = session["user_id"]
    data = request.get_json() or {}
    analysis_data = data.get("analysis")
    if not analysis_data or not isinstance(analysis_data, dict):
        return jsonify({"error": "No analysis data provided"}), 400

    filename = analysis_data.get("filename", "Guest_Resume.pdf")
    job_description = analysis_data.get("job_description", "")
    resume_text = analysis_data.get("raw_text", "")
    content_hash = hashlib.sha256((resume_text or "").encode("utf-8", errors="ignore")).hexdigest()

    try:
        with get_db() as db:
            existing_analysis = db.execute(
                "SELECT id FROM analyses WHERE user_id = ? AND content_hash = ?",
                (user_id, content_hash)
            ).fetchone()

            if existing_analysis:
                analysis_id = existing_analysis["id"]
                db.execute(
                    """UPDATE analyses SET
                        filename = ?, job_description = ?, overall_score = ?,
                        dimension_scores = ?, summary = ?, strengths = ?,
                        weaknesses = ?, missing_sections = ?, ats_issues = ?,
                        suggestions = ?, suggested_keywords = ?, full_json = ?,
                        content_hash = ?, created_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND user_id = ?""",
                    (
                        filename,
                        job_description,
                        analysis_data.get("overall_score", 70),
                        json.dumps(analysis_data.get("dimension_scores", {})),
                        analysis_data.get("summary", ""),
                        json.dumps(analysis_data.get("strengths", [])),
                        json.dumps(analysis_data.get("weaknesses", [])),
                        json.dumps(analysis_data.get("missing_sections", [])),
                        json.dumps(analysis_data.get("ats_issues", [])),
                        json.dumps(analysis_data.get("suggestions", [])),
                        json.dumps(analysis_data.get("suggested_keywords", [])),
                        json.dumps(analysis_data),
                        content_hash,
                        analysis_id,
                        user_id
                    )
                )
            else:
                cursor = db.execute(
                    """INSERT INTO analyses (
                        user_id, filename, job_description, overall_score,
                        dimension_scores, summary, strengths, weaknesses,
                        missing_sections, ats_issues, suggestions, suggested_keywords,
                        full_json, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        filename,
                        job_description,
                        analysis_data.get("overall_score", 70),
                        json.dumps(analysis_data.get("dimension_scores", {})),
                        analysis_data.get("summary", ""),
                        json.dumps(analysis_data.get("strengths", [])),
                        json.dumps(analysis_data.get("weaknesses", [])),
                        json.dumps(analysis_data.get("missing_sections", [])),
                        json.dumps(analysis_data.get("ats_issues", [])),
                        json.dumps(analysis_data.get("suggestions", [])),
                        json.dumps(analysis_data.get("suggested_keywords", [])),
                        json.dumps(analysis_data),
                        content_hash
                    )
                )
                analysis_id = cursor.lastrowid
            analysis_data["id"] = analysis_id

            existing = db.execute(
                "SELECT id FROM resumes WHERE user_id = ? AND filename = ?",
                (user_id, filename)
            ).fetchone()

            data_payload = json.dumps({
                "fullName": filename.rsplit('.', 1)[0],
                "summary": analysis_data.get("summary", ""),
                "skills": ", ".join(analysis_data.get("suggested_keywords", [])),
                "experience": analysis_data.get("experience", []),
                "education": analysis_data.get("education", []),
                "projects": analysis_data.get("projects", []),
                "certifications": analysis_data.get("certifications", []),
                "customSections": analysis_data.get("customSections", []),
                "rawText": resume_text
            })

            if existing:
                db.execute(
                    """UPDATE resumes SET 
                        title = ?, overall_score = ?, analysis_json = ?, data_json = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = ? AND user_id = ?""",
                    (filename, analysis_data.get("overall_score", 70), json.dumps(analysis_data), data_payload, existing["id"], user_id)
                )
                analysis_data["resume_id"] = existing["id"]
            else:
                res_cur = db.execute(
                    """INSERT INTO resumes (
                        user_id, title, filename, template, overall_score, analysis_json, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, filename, filename, 'modern', analysis_data.get("overall_score", 70), json.dumps(analysis_data), data_payload)
                )
                analysis_data["resume_id"] = res_cur.lastrowid
            db.commit()

        return jsonify(analysis_data)
    except Exception as e:
        return jsonify({"error": f"Claim failed: {str(e)}"}), 500


@analysis_bp.route("/api/analyses", methods=["GET"])
@login_required
def get_analyses():
    user_id = session["user_id"]
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT id, filename, overall_score, summary, created_at FROM analyses WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analysis_bp.route("/api/analyses/<int:analysis_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def handle_analysis(analysis_id):
    user_id = session["user_id"]
    method = request.method

    try:
        with get_db() as db:
            if method == "GET":
                r = db.execute(
                    "SELECT * FROM analyses WHERE id = ? AND user_id = ?",
                    (analysis_id, user_id)
                ).fetchone()
                if not r:
                    return jsonify({"error": "Analysis not found or unauthorized"}), 404

                try:
                    # Check if full_json column is present and has data
                    columns = r.keys()
                    if "full_json" in columns and r["full_json"]:
                        result = json.loads(r["full_json"])
                        result["id"] = r["id"]
                        result["filename"] = r["filename"]
                        result["job_description"] = r["job_description"]
                        result["created_at"] = r["created_at"]
                        return jsonify(normalize_analysis_dict(result))
                except Exception:
                    pass

                raw_dict = {
                    "id": r["id"],
                    "filename": r["filename"],
                    "job_description": r["job_description"],
                    "overall_score": r["overall_score"],
                    "dimension_scores": json.loads(r["dimension_scores"]) if r["dimension_scores"] else {},
                    "summary": r["summary"],
                    "strengths": json.loads(r["strengths"]) if r["strengths"] else [],
                    "weaknesses": json.loads(r["weaknesses"]) if r["weaknesses"] else [],
                    "missing_sections": json.loads(r["missing_sections"]) if r["missing_sections"] else [],
                    "ats_issues": json.loads(r["ats_issues"]) if r["ats_issues"] else [],
                    "suggestions": json.loads(r["suggestions"]) if r["suggestions"] else [],
                    "suggested_keywords": json.loads(r["suggested_keywords"]) if r["suggested_keywords"] else [],
                    "created_at": r["created_at"]
                }
                result = normalize_analysis_dict(raw_dict)
                result["id"] = r["id"]
                result["filename"] = r["filename"]
                return jsonify(result)

            elif method == "PUT":
                data = request.get_json() or {}
                new_filename = data.get("filename", "").strip()
                if not new_filename:
                    return jsonify({"error": "New filename is required"}), 400
                row = db.execute(
                    "SELECT filename FROM analyses WHERE id = ? AND user_id = ?",
                    (analysis_id, user_id)
                ).fetchone()
                if not row:
                    return jsonify({"error": "Analysis not found"}), 404
                old_filename = row["filename"]
                db.execute(
                    "UPDATE analyses SET filename = ? WHERE id = ? AND user_id = ?",
                    (new_filename, analysis_id, user_id)
                )
                if old_filename and old_filename != new_filename:
                    db.execute(
                        "UPDATE resumes SET title = ?, filename = ? WHERE user_id = ? AND filename = ?",
                        (new_filename, new_filename, user_id, old_filename)
                    )
                db.commit()
                return jsonify({"message": "Report renamed successfully"})

            elif method == "DELETE":
                row = db.execute("SELECT filename FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id)).fetchone()
                if not row:
                    return jsonify({"error": "Analysis not found"}), 404
                db.execute("DELETE FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id))
                db.commit()
                return jsonify({"message": f"Report '{row['filename']}' deleted successfully"})
    except Exception as e:
        return jsonify({"error": f"Failed to process analysis: {str(e)}"}), 500


@analysis_bp.route("/api/analyses/<int:analysis_id>/signed-url", methods=["GET"])
@login_required
def get_analysis_signed_url(analysis_id):
    user_id = session["user_id"]
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT file_path, filename FROM analyses WHERE id = ? AND user_id = ?",
                (analysis_id, user_id)
            ).fetchone()
            if not row or not row["file_path"]:
                return jsonify({"error": "File path not found for this analysis"}), 404

            from backend.services.supabase_service import get_signed_resume_url
            url = get_signed_resume_url(row["file_path"], expires_in=3600)
            if not url:
                return jsonify({"error": "Failed to generate signed URL"}), 500

            return jsonify({"url": url, "filename": row["filename"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
