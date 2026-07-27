import json
from flask import Blueprint, request, jsonify, session
from backend.database import get_db
from backend.decorators import login_required
from backend.services.ai import call_groq

builder_bp = Blueprint("builder", __name__)


@builder_bp.route("/api/builder/ai-assist", methods=["POST"])
@login_required
def builder_ai_assist():
    data = request.get_json() or {}
    action = data.get("action", "improve_bullet")
    text = data.get("text", "").strip()
    target_role = data.get("target_role", "").strip()

    if not text and action != "generate_summary":
        return jsonify({"error": "No text provided for AI processing"}), 400

    prompt_templates = {
        "improve_bullet": "You are a professional resume writer. Rewrite the following resume bullet point to make it high-impact, ATS-optimized, and action-oriented using strong verbs. Return ONLY the improved bullet point text, nothing else.\n\nBullet Point: {text}",
        "quantify_bullet": "You are an executive resume coach. Enhance the following resume bullet point by adding realistic quantifiable metrics, percentages, or metrics data. Return ONLY the enhanced bullet point, nothing else.\n\nBullet Point: {text}",
        "fix_grammar": "You are a professional editor. Correct all grammar, spelling, and phrasing errors in the following text. Keep the tone professional. Return ONLY the corrected text, nothing else.\n\nText: {text}",
        "generate_summary": "You are a professional executive resume writer. Write a compelling 3-sentence ATS-friendly professional summary for a candidate applying for the role of '{target_role}'. Context: {text}. Return ONLY the 3-sentence summary, nothing else.",
        "ats_polish": "You are an ATS optimization specialist. Polish the following text for maximum keyword compatibility and clarity. Return ONLY the polished text, nothing else.\n\nText: {text}"
    }

    template = prompt_templates.get(action, prompt_templates["improve_bullet"])
    prompt = template.format(text=text, target_role=target_role or "Professional")

    try:
        ai_response = call_groq(prompt, max_tokens=300).strip()
        if ai_response.startswith('"') and ai_response.endswith('"'):
            ai_response = ai_response[1:-1].strip()
        return jsonify({"result": ai_response})
    except Exception as e:
        return jsonify({"error": f"AI assistance failed: {str(e)}"}), 500


@builder_bp.route("/api/resumes", methods=["GET", "POST"])
@login_required
def handle_resumes():
    user_id = session["user_id"]
    with get_db() as db:
        if request.method == "GET":
            db.execute("""
                DELETE FROM resumes 
                WHERE user_id = ? AND (
                    TRIM(title) LIKE 'My Master Resume%' 
                    OR data_json LIKE '%John Doe%'
                    OR (data_json = '{}' OR data_json IS NULL OR data_json = '')
                )
            """, (user_id,))
            db.execute("DELETE FROM analyses WHERE user_id = ? AND filename LIKE 'My Master Resume%'", (user_id,))

            db.execute("""
                INSERT INTO resumes (user_id, title, filename, template, overall_score, analysis_json, data_json)
                SELECT a.user_id, a.filename, a.filename, 'modern', a.overall_score, 
                       json_object(
                           'id', a.id, 'filename', a.filename,
                           'overall_score', a.overall_score, 'summary', a.summary,
                           'job_description', a.job_description,
                           'dimension_scores', json(a.dimension_scores),
                           'strengths', json(a.strengths), 'weaknesses', json(a.weaknesses),
                           'missing_sections', json(a.missing_sections),
                           'ats_issues', json(a.ats_issues), 'suggestions', json(a.suggestions),
                           'suggested_keywords', json(a.suggested_keywords),
                           'created_at', a.created_at
                       ),
                       json_object('fullName', REPLACE(a.filename, '.pdf', ''), 'summary', a.summary)
                FROM analyses a
                WHERE a.user_id = ? AND NOT EXISTS (
                    SELECT 1 FROM resumes r WHERE r.user_id = a.user_id AND (r.filename = a.filename OR r.title = a.filename)
                )
            """, (user_id,))
            db.commit()

            rows = db.execute(
                "SELECT id, title, filename, template, overall_score, analysis_json, data_json, created_at, updated_at FROM resumes WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["data"] = json.loads(item["data_json"]) if item.get("data_json") else {}
                item["analysis"] = json.loads(item["analysis_json"]) if item.get("analysis_json") else None
                if "data_json" in item: del item["data_json"]
                if "analysis_json" in item: del item["analysis_json"]
                results.append(item)
            return jsonify(results)
        else:
            data = request.get_json() or {}
            title = data.get("title", "Untitled Resume").strip()
            template = data.get("template", "modern")
            data_json = json.dumps(data.get("data", {}))
            cursor = db.execute(
                "INSERT INTO resumes (user_id, title, template, data_json) VALUES (?, ?, ?, ?)",
                (user_id, title, template, data_json)
            )
            db.commit()
            return jsonify({"message": "Resume draft created", "id": cursor.lastrowid})


@builder_bp.route("/api/resumes/<int:resume_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def handle_resume_detail(resume_id):
    user_id = session["user_id"]
    with get_db() as db:
        if request.method == "GET":
            row = db.execute(
                "SELECT id, title, template, data_json, created_at, updated_at FROM resumes WHERE id = ? AND user_id = ?",
                (resume_id, user_id)
            ).fetchone()
            if not row:
                return jsonify({"error": "Resume draft not found"}), 404
            res_dict = dict(row)
            res_dict["data"] = json.loads(res_dict["data_json"])
            del res_dict["data_json"]
            return jsonify(res_dict)

        elif request.method == "PUT":
            data = request.get_json() or {}
            title = data.get("title", "Untitled Resume").strip()
            template = data.get("template", "modern")
            data_json = json.dumps(data.get("data", {}))
            res = db.execute(
                "UPDATE resumes SET title = ?, template = ?, data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (title, template, data_json, resume_id, user_id)
            )
            db.commit()
            if res.rowcount == 0:
                return jsonify({"error": "Resume draft not found"}), 404
            return jsonify({"message": "Resume saved successfully"})

        elif request.method == "DELETE":
            row = db.execute("SELECT filename, title FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)).fetchone()
            if row:
                fname = row["filename"] or row["title"]
                db.execute("DELETE FROM analyses WHERE user_id = ? AND filename = ?", (user_id, fname))
            res = db.execute("DELETE FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id))
            db.commit()
            if res.rowcount == 0:
                return jsonify({"error": "Resume not found"}), 404
            return jsonify({"message": "Resume deleted successfully"})


@builder_bp.route("/api/resumes/<int:resume_id>/duplicate", methods=["POST"])
@login_required
def duplicate_resume(resume_id):
    user_id = session["user_id"]
    with get_db() as db:
        row = db.execute(
            "SELECT title, filename, template, data_json, overall_score, analysis_json FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user_id)
        ).fetchone()
        if not row:
            return jsonify({"error": "Resume not found"}), 404
        new_title = f"Copy of {row['title']}"
        cursor = db.execute(
            "INSERT INTO resumes (user_id, title, filename, template, data_json, overall_score, analysis_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, new_title, row["filename"], row["template"], row["data_json"], row["overall_score"], row["analysis_json"])
        )
        db.commit()
        return jsonify({"message": "Resume duplicated successfully", "id": cursor.lastrowid})
