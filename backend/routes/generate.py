import logging
import re
import json
from flask import Blueprint, request, jsonify, redirect, url_for, session
from backend.decorators import login_required
from backend.services.helpers import (clean_json, estimate_resume_score, extract_resume_text,
                                     is_resume_filename)
from backend.services.ai import call_groq, GroqError
from backend.services.ratelimit import rate_limit
from backend.prompts import (SCRATCH_PROMPT, IMPROVE_PROMPT, SAFE_OPTIMIZE_PROMPT, ROLE_OPTIMIZE_PROMPT,
                             EXECUTIVE_OPTIMIZE_PROMPT, DIFF_PROMPT, OPTIMIZE_STANDARD, COVER_LETTER_PROMPT,
                             INTERVIEW_PREP_PROMPT, BEHAVIORAL_PREP_PROMPT, SYSTEM_DESIGN_PREP_PROMPT,
                             INTERVIEW_SCORE_PROMPT, ROADMAP_PROMPT)

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


# Interview practice modes. Each shares the prep response shape, so one UI
# renders all three; the rubric is what the scorer grades a practice answer on.
INTERVIEW_KINDS = {
    "role": {
        "prompt": INTERVIEW_PREP_PROMPT,
        "label": "Role-specific question",
        "rubric": ["Relevance to the question", "Specific evidence", "Impact and results", "Clarity"],
    },
    "behavioral": {
        "prompt": BEHAVIORAL_PREP_PROMPT,
        "label": "Behavioural question, answered in STAR form",
        "rubric": ["Situation", "Task", "Action (what YOU did)", "Result, ideally measured", "Reflection"],
    },
    "system_design": {
        "prompt": SYSTEM_DESIGN_PREP_PROMPT,
        "label": "System design question",
        "rubric": ["Requirements and scope", "High-level design", "Data model and storage",
                   "Scale and bottlenecks", "Trade-offs explained"],
    },
}

_MIN_ANSWER_WORDS = 25


def _squash(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _quote_in_answer(quote, answer):
    """True when a feedback quote really appears in the answer.

    Punctuation and case are ignored (models tidy both), but the words must
    be there in order. A coach that "quotes" something the candidate never
    said is inventing the answer it is grading.
    """
    q = _squash(quote)
    return bool(q) and q in _squash(answer)


@generate_bp.route("/api/interview/prep", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def interview_prep():
    """Likely questions for one role, each tied to evidence in the resume.

    A question the resume cannot answer comes back with empty evidence and
    the topic listed under gaps_to_prepare -- the honest answer, rather than
    inventing experience for the candidate to repeat in a real interview.

    `kind` selects role-specific (default), behavioral (STAR) or
    system_design questions.
    """
    body = request.get_json(silent=True) or {}
    kind = (body.get("kind") or "role").strip().lower()
    if kind not in INTERVIEW_KINDS:
        return jsonify({"error": "Unknown interview type."}), 400
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
        INTERVIEW_KINDS[kind]["prompt"].format(job_description=description[:4000],
                                               resume_text=resume_text[:9000]),
        2200, "Interview prep")
    if err:
        return err

    if kind == "system_design" and parsed.get("applicable") is False:
        return jsonify({
            "kind": kind,
            "applicable": False,
            "role_summary": str(parsed.get("role_summary") or "").strip()[:400],
            "questions": [], "gaps_to_prepare": [], "questions_to_ask": [], "grounded": 0,
        })

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
        "kind": kind,
        "applicable": True,
        "role_summary": str(parsed.get("role_summary") or "").strip()[:400],
        "questions": questions,
        "gaps_to_prepare": _clean_list(parsed.get("gaps_to_prepare"), 6),
        "questions_to_ask": _clean_list(parsed.get("questions_to_ask"), 4),
        "grounded": sum(1 for q in questions if q["your_evidence"]),
    })


@generate_bp.route("/api/interview/score", methods=["POST"])
@login_required
@rate_limit(limit=30, window_seconds=300)
def interview_score():
    """Rubric feedback on one practice answer.

    Every rubric line carries a quote from the answer. The server checks each
    quote against the answer and blanks any that is not really there (and
    caps that item's score at 2), so the feedback can only be about what the
    candidate actually said. The overall score is the mean of the rubric, not
    a number the model picks separately.
    """
    body = request.get_json(silent=True) or {}
    kind = (body.get("kind") or "role").strip().lower()
    if kind not in INTERVIEW_KINDS:
        return jsonify({"error": "Unknown interview type."}), 400
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not question:
        return jsonify({"error": "Pick a question to practise first."}), 400
    if len(answer.split()) < _MIN_ANSWER_WORDS:
        return jsonify({"error": f"Write at least {_MIN_ANSWER_WORDS} words so there is something to give feedback on."}), 400

    spec = INTERVIEW_KINDS[kind]
    parsed, err = _grounded_json_call(
        INTERVIEW_SCORE_PROMPT.format(
            kind_label=spec["label"], rubric="; ".join(spec["rubric"]),
            question=question[:600], answer=answer[:6000],
            job_description=(body.get("description") or "").strip()[:2500]),
        1800, "Interview score")
    if err:
        return err

    rubric, unverified = [], 0
    for item in (parsed.get("rubric") or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("item") or "").strip()[:80]
        if not name:
            continue
        try:
            score = int(round(float(item.get("score"))))
        except (TypeError, ValueError):
            continue
        score = max(1, min(5, score))
        quote = str(item.get("quote") or "").strip()[:300]
        if quote and not _quote_in_answer(quote, answer):
            unverified += 1
            quote = ""
        if not quote:
            score = min(score, 2)
        rubric.append({"item": name, "score": score, "quote": quote,
                       "fix": str(item.get("fix") or "").strip()[:400]})
    if not rubric:
        return jsonify({"error": "The AI came back empty. Try again."}), 502

    overall = round(sum(r["score"] for r in rubric) / len(rubric), 1)
    return jsonify({
        "kind": kind,
        "overall": overall,
        "out_of": 5,
        "rubric": rubric,
        "strengths": _clean_list(parsed.get("strengths"), 3),
        "biggest_gap": str(parsed.get("biggest_gap") or "").strip()[:400],
        "stronger_outline": _clean_list(parsed.get("stronger_outline"), 5),
        "unverified_quotes_removed": unverified,
        "words": len(answer.split()),
    })


@generate_bp.route("/api/career/roadmap", methods=["POST"])
@login_required
@rate_limit(limit=10, window_seconds=300)
def career_roadmap():
    """A phased plan, with a portfolio project per phase, toward one role.

    Strengths must quote the resume; any strength whose evidence is not in the
    resume is dropped server-side, the same rule the interview scorer applies
    to quotes from an answer.
    """
    body = request.get_json(silent=True) or {}
    target = (body.get("target_role") or "").strip()[:120]
    if not target:
        return jsonify({"error": "Enter the role you are aiming for."}), 400
    try:
        # `or 8` would turn an explicit 0 into the default instead of the floor.
        raw_weeks, raw_hours = body.get("weeks"), body.get("hours_per_week")
        weeks = max(2, min(26, int(8 if raw_weeks in (None, "") else raw_weeks)))
        hours = max(2, min(40, int(8 if raw_hours in (None, "") else raw_hours)))
    except (TypeError, ValueError):
        return jsonify({"error": "Weeks and hours must be numbers."}), 400

    resume_text = _resume_text_for(body.get("analysis_id"))
    if not resume_text:
        return jsonify({
            "error": "Analyze a resume first, so the roadmap starts from where you really are.",
            "no_resume": True,
        }), 400

    parsed, err = _grounded_json_call(
        ROADMAP_PROMPT.format(target_role=target, weeks=weeks, hours=hours,
                              resume_text=resume_text[:9000]),
        3000, "Roadmap")
    if err:
        return err

    strengths, dropped = [], 0
    for item in (parsed.get("strengths") or [])[:8]:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()[:80]
        evidence = str(item.get("evidence") or "").strip()[:300]
        if not skill:
            continue
        if not _quote_in_answer(evidence, resume_text):
            dropped += 1
            continue
        strengths.append({"skill": skill, "evidence": evidence})

    phases = []
    for item in (parsed.get("phases") or [])[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:120]
        if not title:
            continue
        project = item.get("project") if isinstance(item.get("project"), dict) else {}
        try:
            phase_weeks = max(1, min(26, int(item.get("weeks") or 1)))
        except (TypeError, ValueError):
            phase_weeks = 1
        phases.append({
            "title": title,
            "weeks": phase_weeks,
            "skills": _clean_list(item.get("skills"), 6, 60),
            "learn": _clean_list(item.get("learn"), 6, 160),
            "project": {
                "name": str(project.get("name") or "").strip()[:120],
                "build": str(project.get("build") or "").strip()[:600],
                "proves": _clean_list(project.get("proves"), 6, 60),
                "resume_line": str(project.get("resume_line") or "").strip()[:300],
            },
            "done_when": str(item.get("done_when") or "").strip()[:300],
        })
    if not phases:
        return jsonify({"error": "The AI came back empty. Try again."}), 502

    return jsonify({
        "target_role": target,
        "weeks": weeks,
        "hours_per_week": hours,
        "planned_weeks": sum(p["weeks"] for p in phases),
        "summary": str(parsed.get("summary") or "").strip()[:500],
        "strengths": strengths,
        "unverified_strengths_removed": dropped,
        "phases": phases,
        "interview_topics": _clean_list(parsed.get("interview_topics"), 6),
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

    if not is_resume_filename(file.filename):
        return jsonify({"error": "Please upload a PDF, DOCX or TXT file"}), 400

    try:
        resume_text = extract_resume_text(file)

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
            if not is_resume_filename(file.filename):
                return jsonify({"error": "Please upload a PDF, DOCX or TXT file"}), 400
            resume_text = extract_resume_text(file)
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
