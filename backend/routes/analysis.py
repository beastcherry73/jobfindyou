import json
from flask import Blueprint, request, jsonify, session
from backend.database import get_db
from backend.decorators import login_required
from backend.services.helpers import extract_text_from_pdf, clean_json, normalize_analysis_dict
from backend.services.ai import call_groq
from backend.prompts import ANALYSIS_PROMPT

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("/api/analyze", methods=["POST"])
@login_required
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
            resume_text = f"Sample candidate resume content from {file.filename}"

        job_context = (
            f"The candidate is applying for this role: {job_description}"
            if job_description
            else "No specific job description provided. Give a general analysis."
        )

        prompt = ANALYSIS_PROMPT.format(job_context=job_context, resume_text=resume_text[:12000])
        raw = clean_json(call_groq(prompt))

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}

        result = normalize_analysis_dict(parsed)
        result["filename"] = file.filename
        result["raw_text"] = resume_text

        user_id = session.get("user_id")
        if user_id:
            try:
                with get_db() as db:
                    cursor = db.execute(
                        """INSERT INTO analyses (
                            user_id, filename, job_description, overall_score,
                            dimension_scores, summary, strengths, weaknesses,
                            missing_sections, ats_issues, suggestions, suggested_keywords
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                            json.dumps(result["suggested_keywords"])
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
                        "skills": ", ".join(result.get("suggested_keywords", [])),
                        "rawText": resume_text
                    })

                    if existing:
                        db.execute(
                            """UPDATE resumes SET 
                                title = ?, overall_score = ?, analysis_json = ?, data_json = ?, updated_at = CURRENT_TIMESTAMP 
                                WHERE id = ? AND user_id = ?""",
                            (file.filename, result["overall_score"], json.dumps(result), data_payload, existing["id"], user_id)
                        )
                        result["resume_id"] = existing["id"]
                    else:
                        res_cur = db.execute(
                            """INSERT INTO resumes (
                                user_id, title, filename, template, overall_score, analysis_json, data_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (user_id, file.filename, file.filename, 'modern', result["overall_score"], json.dumps(result), data_payload)
                        )
                        result["resume_id"] = res_cur.lastrowid
                    db.commit()
            except Exception as db_err:
                # Log DB error but still return the analysis result to the user
                import logging
                logging.getLogger(__name__).error(f"Failed to save analysis to DB: {db_err}")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500


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
            analyses = [dict(r) for r in rows]
        return jsonify(analyses)
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
                res = db.execute(
                    "UPDATE analyses SET filename = ? WHERE id = ? AND user_id = ?",
                    (new_filename, analysis_id, user_id)
                )
                db.commit()
                if res.rowcount == 0:
                    return jsonify({"error": "Analysis not found"}), 404
                return jsonify({"message": "Report renamed successfully"})

            elif method == "DELETE":
                row = db.execute("SELECT filename FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id)).fetchone()
                if row and row["filename"]:
                    db.execute("DELETE FROM resumes WHERE user_id = ? AND (filename = ? OR title = ?)", (user_id, row["filename"], row["filename"]))
                cursor = db.execute("DELETE FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id))
                db.commit()
                if cursor.rowcount == 0:
                    return jsonify({"error": "Analysis not found or unauthorized"}), 404
                return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
