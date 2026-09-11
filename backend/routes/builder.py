import json
from flask import Blueprint, request, jsonify, session
from backend.database import get_db
from backend.decorators import login_required
from backend.services.ai import call_groq, GroqError
from backend.services.helpers import clean_json
from backend.services.ratelimit import rate_limit

builder_bp = Blueprint("builder", __name__)


@builder_bp.route("/api/builder/ai-assist", methods=["POST"])
@login_required
@rate_limit(limit=20, window_seconds=300)
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
        try:
            ai_response = call_groq(prompt, max_tokens=300).strip()
        except GroqError:
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502
        if not ai_response or ai_response in ("{}", ""):
            return jsonify({"error": "AI service returned an empty result. Please try again."}), 502
        if ai_response.startswith('"') and ai_response.endswith('"'):
            ai_response = ai_response[1:-1].strip()
        return jsonify({"result": ai_response})
    except Exception as e:
        return jsonify({"error": f"AI assistance failed: {str(e)}"}), 500


# ── Today's goals: do the work, not describe it ────────────────────────────
# Each goal on the Goals page comes from the user's own latest analysis (its
# top fixes, the target role's missing keywords) or their pipeline (a stale
# application). "Work on it with AI" returns the concrete artifact -- rewritten
# lines, keyword placements, a follow-up email -- built from THEIR resume, plus
# a few steps to apply it. It never writes into the resume: the user decides.
#
# The honesty rules are in the prompts because they are the product: no
# invented metrics (bracketed placeholders instead), no skills the resume does
# not support. A resume tool that fabricates experience gets its users caught
# out in interviews.
_GOAL_PROMPTS = {
    "resume_fix": (
        "You are a senior resume editor. The candidate's ATS analysis asked them "
        "to make this improvement:\n\nGOAL: {goal}\n\n"
        "Do the work instead of describing it. Using ONLY facts present in the "
        "resume below, write the exact replacement text they should paste in "
        "(rewritten bullets or a rewritten section). Where a number would "
        "strengthen a line but the resume does not state one, insert a bracketed "
        "placeholder such as [X%] or [N users] for the candidate to fill in. "
        "Never invent figures, employers, tools, titles or dates.\n\n"
        "Return JSON only: {{\"summary\": \"one sentence on what you changed and "
        "why\", \"steps\": [\"2 to 4 short steps to apply it\"], \"draft_label\": "
        "\"a short label for the draft, e.g. Rewritten experience bullets\", "
        "\"draft\": \"the replacement text, plain text, one bullet per line "
        "starting with '- '\"}}\n\nRESUME:\n{resume}"
    ),
    "keywords": (
        "You are a senior resume editor. The candidate's target role asks for "
        "these keywords that their resume does not show: {keywords}.\n\n"
        "For each keyword the resume below can HONESTLY support, write the exact "
        "line to add or edit and say which section it belongs in. For each "
        "keyword the resume gives no evidence for, do NOT add it -- say in one "
        "line what the candidate would need to have actually done to claim it. "
        "Never claim a skill the resume does not support.\n\n"
        "Return JSON only: {{\"summary\": \"one sentence: how many keywords can "
        "be added honestly and how many cannot\", \"steps\": [\"one line per "
        "keyword it could NOT support, saying what evidence is missing\"], "
        "\"draft_label\": \"Lines to add\", \"draft\": \"the lines to add, plain "
        "text, each prefixed with its section in brackets, e.g. [Skills] ...\"}}"
        "\n\nRESUME:\n{resume}"
    ),
    "follow_up": (
        "Write a short, specific follow-up email from a job applicant. They "
        "applied for {role} at {company} on {applied} and have heard nothing. "
        "Under 120 words, warm and direct, no grovelling. Put a subject line "
        "first. Mention ONE concrete, relevant strength taken from the resume "
        "below. Use [Hiring Manager] if no name is known; no other placeholders."
        "\n\nReturn JSON only: {{\"summary\": \"one sentence on when and where "
        "to send it\", \"steps\": [\"2 or 3 short steps, e.g. where to find the "
        "recruiter's address\"], \"draft_label\": \"Follow-up email\", "
        "\"draft\": \"Subject: ...\\n\\n...\"}}\n\nRESUME:\n{resume}"
    ),
}


@builder_bp.route("/api/goals/assist", methods=["POST"])
@login_required
@rate_limit(limit=15, window_seconds=300)
def goals_assist():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    goal = str(data.get("goal") or "").strip()[:500]
    if kind not in _GOAL_PROMPTS or not goal:
        return jsonify({"error": "Unknown goal."}), 400

    # Lazy import: jobs.py is a sibling route module; importing at load time
    # would couple the two blueprints' import order for no benefit.
    from backend.routes.jobs import _latest_resume_text
    resume_text = (_latest_resume_text(session["user_id"]) or "").strip()
    if not resume_text:
        return jsonify({"error": "Analyze a resume first. Goals work from your latest resume."}), 400

    keywords = data.get("keywords") if isinstance(data.get("keywords"), list) else []
    prompt = _GOAL_PROMPTS[kind].format(
        goal=goal,
        keywords=", ".join(str(k)[:60] for k in keywords[:8]) or goal,
        role=str(data.get("role") or "the role")[:120],
        company=str(data.get("company") or "the company")[:120],
        applied=str(data.get("applied") or "recently")[:40],
        resume=resume_text[:9000],
    )
    try:
        raw = clean_json(call_groq(prompt, max_tokens=1800, json_mode=True))
    except GroqError:
        return jsonify({"error": "The AI service is busy right now. Try again in a minute."}), 502
    try:
        out = json.loads(raw)
    except Exception:
        out = None
    if not isinstance(out, dict):
        return jsonify({"error": "The AI returned something unreadable. Try again."}), 502

    steps = out.get("steps") if isinstance(out.get("steps"), list) else []
    result = {
        "summary": str(out.get("summary") or "").strip()[:600],
        "steps": [str(s).strip()[:300] for s in steps if str(s).strip()][:6],
        "draft_label": str(out.get("draft_label") or "").strip()[:80],
        "draft": str(out.get("draft") or "").strip()[:4000],
    }
    if not (result["summary"] or result["draft"]):
        return jsonify({"error": "The AI came back empty. Try again."}), 502
    return jsonify(result)


@builder_bp.route("/api/resumes", methods=["GET", "POST"])
@login_required
def handle_resumes():
    user_id = session["user_id"]
    with get_db() as db:
        if request.method == "GET":
            try:
                # Auto-sync analyses to resumes safely across SQLite and PostgreSQL
                existing_rows = db.execute("SELECT filename, title FROM resumes WHERE user_id = ?", (user_id,)).fetchall()
                existing_names = set()
                for er in existing_rows:
                    if er["filename"]: existing_names.add(er["filename"])
                    if er["title"]: existing_names.add(er["title"])

                # Only analyses with no resume row yet need their full JSON.
                # This used to SELECT * across every analysis on EVERY
                # versions/history load - shipping each full report over the
                # wire just to discover the (almost always zero) unmapped ones.
                id_rows = db.execute(
                    "SELECT id, filename FROM analyses WHERE user_id = ?", (user_id,)
                ).fetchall()
                missing_ids = [r["id"] for r in id_rows
                               if r["filename"] and r["filename"] not in existing_names]
                unmapped_analyses = []
                if missing_ids:
                    marks = ", ".join(["?"] * len(missing_ids))
                    unmapped_analyses = db.execute(
                        f"SELECT * FROM analyses WHERE user_id = ? AND id IN ({marks})",
                        [user_id] + missing_ids,
                    ).fetchall()
                for a in unmapped_analyses:
                    fname = a["filename"]
                    if fname and fname not in existing_names:
                        a_dict = {
                            "id": a["id"],
                            "filename": fname,
                            "overall_score": a["overall_score"],
                            "summary": a["summary"],
                            "job_description": a["job_description"],
                            "created_at": a["created_at"]
                        }
                        clean_name = fname.rsplit('.', 1)[0] if '.' in fname else fname
                        full_json = {}
                        try:
                            full_json = json.loads(a["full_json"]) if a.get("full_json") else {}
                        except Exception:
                            full_json = {}
                        data_payload = json.dumps({
                            "fullName": clean_name,
                            "summary": full_json.get("summary") or a["summary"],
                            "skills": full_json.get("skills") or ", ".join(full_json.get("suggested_keywords", [])),
                            "experience": full_json.get("experience", []),
                            "education": full_json.get("education", []),
                            "projects": full_json.get("projects", []),
                            "certifications": full_json.get("certifications", []),
                            "rawText": ""
                        })
                        db.execute(
                            """INSERT INTO resumes (user_id, title, filename, template, overall_score, analysis_json, data_json)
                               VALUES (?, ?, ?, 'modern', ?, ?, ?)""",
                            (user_id, fname, fname, a["overall_score"], json.dumps(a_dict), data_payload)
                        )
                        existing_names.add(fname)
                db.commit()
            except Exception as sync_err:
                import logging
                logging.getLogger(__name__).warning(f"Resumes auto-sync error: {sync_err}")

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
