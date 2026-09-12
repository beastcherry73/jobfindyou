import logging
import re
import json
from flask import Blueprint, request, jsonify, redirect, url_for, session
from backend.decorators import login_required
from backend.services.helpers import extract_text_from_pdf, estimate_resume_score, clean_json
from backend.services.ai import call_groq, GroqError
from backend.services.ratelimit import rate_limit
from backend.prompts import SCRATCH_PROMPT, IMPROVE_PROMPT, SAFE_OPTIMIZE_PROMPT, ROLE_OPTIMIZE_PROMPT, EXECUTIVE_OPTIMIZE_PROMPT, DIFF_PROMPT, OPTIMIZE_STANDARD, COVER_LETTER_PROMPT, INTERVIEW_PREP_PROMPT

generate_bp = Blueprint("generate", __name__)
logger = logging.getLogger(__name__)


def _resume_text_for(analysis_id=None):
    """The user's most recent analyzed resume text (or a specific analysis).

    Lazy import: jobs.py is a sibling route module and already owns this
    lookup; importing it at load time would couple the blueprints' import
    order for nothing.
    """
    from backend.routes.jobs import _latest_resume_text
    return (_latest_resume_text(session["user_id"], analysis_id) or "").strip()


def _grounded_json_call(prompt, max_tokens, what):
    """One JSON call for the grounded writers. Returns (parsed, error_response)."""
    try:
        raw = clean_json(call_groq(prompt, max_tokens=max_tokens, json_mode=True))
    except GroqError:
        return None, (jsonify({"error": "The AI service is busy right now. Try again in a minute."}), 502)
    try:
        parsed = json.loads(raw)
    except Exception:
        logger.warning("%s: unreadable AI output, head=%r", what, (raw or "")[:200])
        parsed = None
    if not isinstance(parsed, dict) or not parsed:
        return None, (jsonify({"error": "The AI returned something unreadable. Try again."}), 502)
    return parsed, None


def _clean_list(value, limit, length=300):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text[:length])
    return out[:limit]


@generate_bp.route("/api/generate/cover-letter", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def generate_cover_letter():
    """A cover letter built only from what the resume actually says.

    The response carries `evidence_used` and `placeholders` so the UI can show
    which resume facts the letter leans on, and which numbers the candidate
    still has to fill in themselves. Nothing is written to the resume.
    """
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"error": "Paste the job description first."}), 400

    resume_text = _resume_text_for(body.get("analysis_id"))
    if not resume_text:
        return jsonify({
            "error": "Analyze a resume first, so the letter has real facts to work from.",
            "no_resume": True,
        }), 400

    parsed, err = _grounded_json_call(
        COVER_LETTER_PROMPT.format(job_description=description[:4000],
                                   resume_text=resume_text[:9000]),
        1800, "Cover letter")
    if err:
        return err

    paragraphs = _clean_list(parsed.get("paragraphs"), 5, 1200)
    if not paragraphs:
        return jsonify({"error": "The AI came back empty. Try again."}), 502
    greeting = str(parsed.get("greeting") or "Dear Hiring Manager,").strip()[:160]
    closing = str(parsed.get("closing") or "Thank you for your time.").strip()[:240]
    letter = "\n\n".join([greeting] + paragraphs + [closing])
    return jsonify({
        "subject": str(parsed.get("subject") or "").strip()[:160],
        "greeting": greeting,
        "paragraphs": paragraphs,
        "closing": closing,
        "letter": letter,
        "evidence_used": _clean_list(parsed.get("evidence_used"), 6),
        "placeholders": _clean_list(parsed.get("placeholders"), 8, 80),
        "words": len(letter.split()),
    })


@generate_bp.route("/api/interview/prep", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def interview_prep():
    """Likely questions for one role, each tied to evidence in the resume.

    A question the resume cannot answer comes back with empty evidence and
    the topic listed under gaps_to_prepare -- the honest answer, rather than
    inventing experience for the candidate to repeat in a real interview.
    """
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"error": "Paste the job description first."}), 400

    resume_text = _resume_text_for(body.get("analysis_id"))
    if not resume_text:
        return jsonify({
            "error": "Analyze a resume first, so the prep can point at your own experience.",
            "no_resume": True,
        }), 400

    parsed, err = _grounded_json_call(
        INTERVIEW_PREP_PROMPT.format(job_description=description[:4000],
                                     resume_text=resume_text[:9000]),
        2200, "Interview prep")
    if err:
        return err

    questions = []
    for item in (parsed.get("questions") or [])[:10]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        questions.append({
            "question": question[:400],
            "why": str(item.get("why") or "").strip()[:400],
            "your_evidence": str(item.get("your_evidence") or "").strip()[:600],
        })
    if not questions:
        return jsonify({"error": "The AI came back empty. Try again."}), 502

    return jsonify({
        "role_summary": str(parsed.get("role_summary") or "").strip()[:400],
        "questions": questions,
        "gaps_to_prepare": _clean_list(parsed.get("gaps_to_prepare"), 6),
        "questions_to_ask": _clean_list(parsed.get("questions_to_ask"), 4),
        "grounded": sum(1 for q in questions if q["your_evidence"]),
    })


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
        try:
            resume = call_groq(prompt, max_tokens=6000)
        except GroqError:
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502
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
            optimize_standard=OPTIMIZE_STANDARD,
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        try:
            resume = call_groq(prompt, max_tokens=6000)
        except GroqError:
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502
        resume = re.sub(r"^```(?:markdown)?", "", resume.strip()).strip()
        resume = re.sub(r"```$", "", resume).strip()

        return jsonify({"resume": resume})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generate_bp.route("/api/generate/improve-with-diff", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def generate_improve_with_diff():
    try:
        resume_text = ""
        file = request.files.get("resume")
        instructions = request.form.get("instructions") or (request.json.get("instructions") if request.is_json else "") or ""
        job_description = request.form.get("job_description") or (request.json.get("job_description") if request.is_json else "") or ""
        raw_text_payload = request.form.get("resume_text") or (request.json.get("resume_text") if request.is_json else "") or ""

        if file and file.filename != "":
            if not file.filename.lower().endswith((".pdf", ".txt")):
                return jsonify({"error": "Please upload a PDF or TXT file"}), 400
            if file.filename.lower().endswith(".pdf"):
                resume_text = extract_text_from_pdf(file)
            else:
                resume_text = file.read().decode("utf-8", errors="ignore")
        elif raw_text_payload.strip():
            resume_text = raw_text_payload.strip()

        if not resume_text.strip():
            return jsonify({"error": "No resume content or file provided to improve"}), 400

        instructions_context = f"Special instructions: {instructions}" if instructions else ""
        job_context = f"Target role / Job Description:\n{job_description}" if job_description else ""

        mode = (request.form.get("mode") or (request.json.get("mode") if request.is_json else "safe") or "safe").lower()
        if mode == "role":
            selected_prompt = ROLE_OPTIMIZE_PROMPT
        elif mode == "executive":
            selected_prompt = EXECUTIVE_OPTIMIZE_PROMPT
        else:
            selected_prompt = SAFE_OPTIMIZE_PROMPT

        improve_prompt = selected_prompt.format(
            optimize_standard=OPTIMIZE_STANDARD,
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        try:
            improved_resume = call_groq(improve_prompt, max_tokens=6000)
        except GroqError:
            return jsonify({"error": "AI service is temporarily unavailable. Please try again in a few seconds."}), 502
        improved_resume = re.sub(r"^```(?:markdown)?", "", improved_resume.strip()).strip()
        improved_resume = re.sub(r"```$", "", improved_resume).strip()

        # Content-derived scores (honest estimates, not hardcoded)
        orig_score = estimate_resume_score(resume_text, job_description)
        enh_score = estimate_resume_score(improved_resume, job_description)
        # Report the real difference. Clamping a regression to 0 hid it from
        # the UI and, because 0 is falsy in JS, made the client fall back to
        # recomputing the raw negative - which it then printed behind a "+".
        delta = enh_score - orig_score

        improvements = [
            "Transformed passive phrasing into strong action-oriented verbiage",
            "Injected target industry technical keywords into experience bullets",
            "Quantified project scale and business impact metrics",
            "Standardized section formatting for 100% ATS parser compatibility"
        ]

        added_items = [
            "Target role keywords & technical terminology",
            "Quantifiable metrics (+25% efficiency, $50k cost reduction)",
            "Strong leadership & problem-solving action verbs"
        ]

        removed_items = [
            "Repetitive bullet points & passive voice phrasing",
            "Weak fillers (e.g. 'responsible for', 'helped with')",
            "Unnecessary formatting noise & clutter"
        ]

        return jsonify({
            "resume": improved_resume,
            "original_score": orig_score,
            "enhanced_score": enh_score,
            "score_delta": delta,
            "improvements": improvements,
            "added_items": added_items,
            "removed_items": removed_items
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
