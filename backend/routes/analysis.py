import json
import hashlib
from flask import Blueprint, request, jsonify, session
from backend.database import get_db
from backend.decorators import login_required
from backend.services.helpers import extract_text_from_pdf, clean_json, normalize_analysis_dict
from backend.services.ai import call_groq, GroqError
from backend.services.ratelimit import rate_limit
from backend.prompts import ANALYSIS_PROMPT

analysis_bp = Blueprint("analysis", __name__)


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

        prompt = ANALYSIS_PROMPT.format(job_context=job_context, resume_text=resume_text[:12000])
        try:
            raw = clean_json(call_groq(prompt))
        except GroqError:
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}

        if not isinstance(parsed, dict) or not parsed:
            return jsonify({"error": "AI service returned an empty result. Please try again."}), 502

        result = normalize_analysis_dict(parsed)
        result["filename"] = file.filename
        result["raw_text"] = resume_text

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
