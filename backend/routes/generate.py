import re
import json
from flask import Blueprint, request, jsonify, redirect, url_for
from backend.decorators import login_required
from backend.services.helpers import extract_text_from_pdf
from backend.services.ai import call_groq
from backend.prompts import SCRATCH_PROMPT, IMPROVE_PROMPT, SAFE_OPTIMIZE_PROMPT, ROLE_OPTIMIZE_PROMPT, EXECUTIVE_OPTIMIZE_PROMPT, DIFF_PROMPT

generate_bp = Blueprint("generate", __name__)


@generate_bp.route("/generate")
@login_required
def generate():
    return redirect(url_for("static_routes.index"))


@generate_bp.route("/api/generate/scratch", methods=["POST"])
@login_required
def generate_scratch():
    try:
        data = request.get_json()
        if not data or not data.get("name"):
            return jsonify({"error": "Name is required"}), 400

        target_context = (
            f"Tailor the resume for this role:\n{data['targetRole']}"
            if data.get("targetRole")
            else "Write a general professional resume."
        )

        data_str = json.dumps(data, indent=2)
        prompt = SCRATCH_PROMPT.format(target_context=target_context, data=data_str)
        resume = call_groq(prompt, max_tokens=3000)
        resume = re.sub(r"^```(?:markdown)?", "", resume.strip()).strip()
        resume = re.sub(r"```$", "", resume).strip()

        return jsonify({"resume": resume})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generate_bp.route("/api/generate/improve", methods=["POST"])
@login_required
def generate_improve():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    instructions = request.form.get("instructions", "").strip()
    job_description = request.form.get("job_description", "").strip()

    if not file.filename.lower().endswith((".pdf", ".txt")):
        return jsonify({"error": "Please upload a PDF or TXT file"}), 400

    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        else:
            resume_text = file.read().decode("utf-8", errors="ignore")

        if not resume_text.strip():
            return jsonify({"error": "Couldn't extract text from this file"}), 400

        instructions_context = f"Special instructions: {instructions}" if instructions else ""
        job_context = f"Target role:\n{job_description}" if job_description else ""

        prompt = IMPROVE_PROMPT.format(
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        resume = call_groq(prompt, max_tokens=3000)
        resume = re.sub(r"^```(?:markdown)?", "", resume.strip()).strip()
        resume = re.sub(r"```$", "", resume).strip()

        return jsonify({"resume": resume})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generate_bp.route("/api/generate/improve-with-diff", methods=["POST"])
@login_required
def generate_improve_with_diff():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    instructions = request.form.get("instructions", "").strip()
    job_description = request.form.get("job_description", "").strip()

    if not file.filename.lower().endswith((".pdf", ".txt")):
        return jsonify({"error": "Please upload a PDF or TXT file"}), 400

    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        else:
            resume_text = file.read().decode("utf-8", errors="ignore")

        if not resume_text.strip():
            return jsonify({"error": "Couldn't extract text from this file"}), 400

        instructions_context = f"Special instructions: {instructions}" if instructions else ""
        job_context = f"Target role:\n{job_description}" if job_description else ""

        mode = request.form.get("mode", "safe").lower()
        if mode == "role":
            selected_prompt = ROLE_OPTIMIZE_PROMPT
        elif mode == "executive":
            selected_prompt = EXECUTIVE_OPTIMIZE_PROMPT
        else:
            selected_prompt = SAFE_OPTIMIZE_PROMPT

        improve_prompt = selected_prompt.format(
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        improved_resume = call_groq(improve_prompt, max_tokens=3000)
        improved_resume = re.sub(r"^```(?:markdown)?", "", improved_resume.strip()).strip()
        improved_resume = re.sub(r"```$", "", improved_resume).strip()

        improvements = [
            "Rewrote bullet points with stronger action verbs",
            "Added impact-driven language and quantifiable results where possible",
            "Fixed ATS formatting for better parser compatibility",
            "Improved overall clarity and professional tone",
            "Restructured sections to follow standard resume conventions"
        ]
        return jsonify({"resume": improved_resume, "improvements": improvements})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
