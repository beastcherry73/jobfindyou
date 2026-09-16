REFERENCE_STANDARD = """REFERENCE STANDARD — what a top-1% resume actually does (score and critique against THIS bar, not a lenient one):

IMPACT & EVIDENCE
- Every experience bullet leads with a strong action verb and states a measurable outcome, not a duty. "Responsible for X" is a failure; "Cut X 40% by doing Y" is the bar.
- Roughly two-thirds or more of bullets carry a hard number ($ saved, % changed, scale, time, volume, headcount). A resume with no metrics is weak no matter how senior.
- Scope is explicit: team size, user/revenue scale, system throughput — the reader must grasp the magnitude.

STRUCTURE & ATS
- Clean reverse-chronological order; standard section headings (Summary, Experience, Skills, Education, Projects); no tables, columns, text boxes, headers/footers, or graphics that break ATS parsing.
- A complete contact header (name, email, phone, location, and a relevant link). One page for <10 yrs experience, two pages max otherwise.
- A tight professional summary (2-3 lines) that names the role/domain and the candidate's strongest proof — not generic adjectives ("hardworking team player").

LANGUAGE & KEYWORDS
- Active voice throughout; no passive phrasing, no first-person pronouns, no filler ("various", "etc.", "duties included").
- Concrete role-relevant keywords/tools appear naturally in context, not keyword-stuffed into a list divorced from evidence.
- Consistent tense (past for prior roles, present for current), consistent date and formatting conventions.

EXEMPLAR TRANSFORMATIONS (weak -> strong, use as the calibration bar):
- "Worked on the checkout flow and improved performance." -> "Rebuilt the checkout flow, cutting p95 latency from 800ms to 120ms and drop-off 18% for 2M monthly users."
- "Responsible for managing the data team." -> "Led a 6-engineer data team; shipped a real-time pipeline processing 10TB/day, reducing reporting lag from 24h to 15min."
- "Helped with AWS migration." -> "Drove migration of 40+ services to AWS/Kubernetes, cutting infra cost 22% ($200K/yr) with zero downtime."

Hold the candidate's resume to this standard. Do not inflate scores for effort or seniority — score the evidence actually on the page.

"""

ANALYSIS_PROMPT = """You are an elite executive tech recruiter and ATS optimization director. Perform a rigorous, multi-dimension analysis of the candidate's resume and return ONLY a valid JSON object.

{reference_standard}

First, check whether the text below is actually a resume/CV at all (a document describing one person's work experience, education, or skills for the purpose of job applications). It is common for people to accidentally upload the wrong file — a report, an article, a recipe, a job description, random text, etc.

Keys required in JSON response:
- is_resume (boolean — false if the text is clearly not a resume/CV. When false, every other field should still be filled with safe defaults, but strengths, weaknesses, and priority_action_list MUST be empty arrays — never invent specific praise or criticism for content that isn't a resume)
- overall_score (integer 0-100)
- dimension_scores (object with integer 0-100 values for clarity, experience, skills, ats_readiness, impact, completeness)
- summary (string, concise recruiter verdict)
- recruiter_verdict (object with keys: decision, top_standout, biggest_weakness, priority_fix)
- recruiter_first_impression (object with keys: score, readability, visual_organization, likelihood_to_read_on)
- ats_breakdown (object with keys: formatting_score, keywords_match_pct, structure_score, machine_readability)
- keyword_analysis (object with keys: matched_keywords, missing_keywords, overused_words, percentage_match)
- impact_analysis (object with keys: verb_strength_score, missing_metrics_count, passive_bullet_count)
- competitiveness (object with keys: junior_readiness, mid_readiness, senior_readiness, faang_readiness, startup_readiness)
- industry_detected (string)
- priority_action_list (array of objects with keys: priority, recommendation, estimated_gain, difficulty, time_required)
- before_after_examples (array of objects with keys: original, improved, explanation)
- roadmap (object with keys: quick_wins_5m, medium_tasks_30m, major_rewrites_2h)
- strengths (array of strings)
- weaknesses (array of strings)
- missing_sections (array of strings)
- ats_issues (array of strings)
- suggestions (array of strings)
- suggested_keywords (array of strings)

And the following Level 5 Analysis fields:
- ats_compatibility (object with keys: overall_ats_score (integer), section_scores (object with keys: formatting, keywords, skills, readability, structure mapping to integers 0-100))
- missing_keywords_categorized (object with keys: missing (array of objects with keys: word, category), weak (array of objects with: word, category), present (array of objects with: word, category), overused (array of objects with: word, category))
- recruiter_simulation (object with keys: read_time_seconds (integer), most_attractive_section (string), weakest_section (string), likelihood_to_read_entire_resume_pct (integer))
- hiring_probability (object with keys: ats_pass_pct (integer), recruiter_callback_pct (integer), interview_pct (integer), offer_pct (integer))
- section_by_section (object with keys: header, summary, experience, projects, education, skills, certifications, achievements, languages. Each key must be an object with: score (integer), strengths (array of strings), weaknesses (array of strings), suggested_rewrite (string))
- bullet_point_analysis (array of objects with keys: original (string), weak_verbs (array of strings), passive_voice (boolean), missing_metrics (boolean), suggested_stronger (string))
- skills_analysis (object with keys: missing_technical (array of strings), missing_soft (array of strings), industry_specific (array of strings), trending (array of strings))
- keyword_optimization (object with keys: matched (array of strings), missing (array of strings), suggested (array of strings))
- formatting_analysis (object with keys: margins (string), fonts (string), spacing (string), length_pages (integer), consistency (string), file_compatibility (string))
- ai_recommendations (object with keys: top_5_fixes (array of strings), quick_wins (array of strings), major_improvements (array of strings), overall_action_plan (string))

{job_context}

Resume:
{resume_text}"""

JOB_MATCH_PROMPT = """You are an ATS keyword-matching engine. Compare the candidate's resume against the target job description and return ONLY a valid JSON object — no prose, no markdown fences.

Keys required in JSON response:
- match_percent (integer 0-100: how well this resume's skills, experience, and keywords align with what the job description asks for. Be honest and specific — do not default to a generic mid-range number)
- matching_keywords (array of strings: skills/technologies/qualifications the job description asks for that ARE present in the resume, ranked most important first, max 15)
- missing_keywords (array of strings: skills/technologies/qualifications the job description asks for that are NOT present anywhere in the resume, ranked most important first, max 10)
- gap_summary (string, one honest paragraph: what would most improve this candidate's fit for this specific role)
- skill_gaps (array of the 3-5 MOST important gaps only — prioritized guidance, never an exhaustive list. Each is an object with keys: skill (string), why_it_matters (string, one sentence on why this role needs it), how_to_address (string, one concrete sentence — e.g. add a bullet quantifying related work, take a specific type of course, or reframe existing experience to surface it))

Job description:
{job_description}

Resume:
{resume_text}"""

SCRATCH_PROMPT = """You are a professional resume writer. Create a polished, ATS-friendly resume in clean Markdown format.

Use this structure:
# Full Name
Contact info line (email | phone | location | linkedin)

## Summary
...

## Experience
### Job Title — Company (Start – End)
- bullet
- bullet

## Education
### Degree — Institution (Year)

## Skills
Comma separated list

## Certifications
List

Rules:
- Use strong action verbs
- Add impact and metrics where possible
- Keep it concise and professional
- Make it ATS-friendly

{target_context}

Here is the candidate's information:
{data}"""

OPTIMIZE_STANDARD = """REFERENCE STANDARD — rewrite the resume so it moves toward how a top-1% resume reads, WITHOUT inventing anything:
- Lead every experience bullet with a strong, specific action verb; kill passive voice, first-person pronouns, and filler ("responsible for", "helped with", "various", "duties included").
- Surface real impact that is ALREADY in the text — pull any existing number, scope, tool, or outcome up into the bullet where it belongs. If the original has no metric, sharpen the verb and specificity; do NOT fabricate a number, percentage, scale, or dollar amount.
- Standard ATS-safe structure and headings; consistent tense and formatting.
- Keep every real fact — companies, dates, tools, awards, certifications — exactly as given.

CALIBRATION (weak -> strong, fact-preserving; note no invented numbers are added where the original had none):
- "Responsible for working on the backend systems." -> "Designed and maintained core backend systems and services."
- "Helped the team with various tasks." -> "Partnered with the engineering team to deliver features and resolve production issues."
- If the original already says "reduced load time by 40%", make it lead: "Cut page load time 40% by optimizing backend queries."

"""

SAFE_OPTIMIZE_PROMPT = """You are an elite executive resume writer and ATS optimization specialist.
Your goal is to optimize the resume below for maximum ATS compatibility, grammar, and professional polish.

{optimize_standard}
STRICT FACT PRESERVATION RULES:
- DO NOT invent fake percentages, metrics, team sizes, or dollar amounts.
- DO NOT invent fake companies, projects, awards, certifications, or employment history.
- DO NOT remove or replace technical keywords (e.g., PingFederate, PingAccess, Okta, SAML, OAuth, OIDC, AWS, Azure, Docker, Kubernetes, Python, Java, etc.).
- DO NOT remove company names, awards, client names, or years of experience.
- Keep all real facts 100% authentic. If metrics are not in the original text, polish the action verbs and clarity without fabricating fake numbers.

IMPROVEMENTS TO APPLY:
- Use strong, dynamic action verbs.
- Fix all grammar, spelling, punctuation, and awkward phrasing.
- Ensure clear section headers (# Summary, ## Professional Experience, ## Core Competencies, ## Projects, ## Education & Certifications).
- Output clean Markdown only. No commentary, no preamble.

{instructions_context}

Original Resume:
{resume_text}"""

ROLE_OPTIMIZE_PROMPT = """You are an ATS Keyword Optimization Consultant and Executive Resume Writer.
Your goal is to tailor the candidate's existing resume to match the target job description while strictly maintaining factual accuracy.

{optimize_standard}
STRICT RULES:
- Reorder and emphasize relevant experience and skills matching the target role.
- DO NOT claim skills or experience the candidate does not possess.
- DO NOT invent fake metrics, companies, or projects.
- Preserve all technical keywords, awards, company names, and certifications.
- Output clean Markdown only.

{job_context}
{instructions_context}

Original Resume:
{resume_text}"""

EXECUTIVE_OPTIMIZE_PROMPT = """You are an Executive Talent Partner and Master Resume Coach.
Your goal is to elevate the resume's tone, executive leadership language, and overall flow.

{optimize_standard}
STRICT RULES:
- Elevate vocabulary to executive C-suite / VP / Senior Director level.
- DO NOT invent fake facts, metrics, or false accomplishments.
- Preserve every technology, award, company name, and certification.
- Output clean Markdown only.

{instructions_context}

Original Resume:
{resume_text}"""

IMPROVE_PROMPT = SAFE_OPTIMIZE_PROMPT

# A cover letter is the easiest place in this product to fabricate a career,
# so the rules against it are the first thing in the prompt and the output
# carries back the resume facts it used, for the UI to show.
COVER_LETTER_PROMPT = """You are a careful career writer. Write a cover letter for the role below using ONLY facts that appear in the candidate's resume.

HARD RULES
- Never invent an employer, job title, date, tool, degree, metric or achievement that is not in the resume.
- Where a number would strengthen a sentence but the resume does not give one, write a bracketed placeholder such as [X%] or [N users] for the candidate to fill in. Never guess a number.
- If the role asks for something the resume does not show, do not claim it. Say what the candidate does have instead.
- 200-280 words, three or four short paragraphs. Plain, direct language.
- Open with the single strongest piece of evidence in the resume for THIS role.
- Banned: "I am writing to apply", "I am excited about this opportunity", flattery of the company, and any adjective about the candidate the resume cannot support.

Return ONLY a valid JSON object:
{{"subject": "short email subject line",
  "greeting": "Dear Hiring Manager, (use a real name only if the job description names one)",
  "paragraphs": ["...", "...", "..."],
  "closing": "sign-off line, without the candidate's name",
  "evidence_used": ["the resume facts this letter is built on"],
  "placeholders": ["every bracketed placeholder you left, if any"]}}

JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}
"""

# Interview prep, grounded in the candidate's own resume. A question the
# resume cannot answer becomes a gap to prepare, never invented experience.
INTERVIEW_PREP_PROMPT = """You are preparing a candidate for an interview for the role below, honestly.

Produce the questions this specific role is likely to ask, and for each, what in THIS candidate's resume they should use as evidence.

HARD RULES
- Ground every "your_evidence" in something actually written in the resume; quote or closely paraphrase it.
- If the resume holds no evidence for a question, set "your_evidence" to "" and put the topic in gaps_to_prepare. Never invent experience, projects, employers or numbers.
- 6 to 8 questions, weighted to what the job description actually emphasises.
- No filler ("tell me about yourself") unless the role genuinely opens that way.

Return ONLY a valid JSON object:
{{"role_summary": "one line on what this interview really tests",
  "questions": [{{"question": "...", "why": "why this role asks it", "your_evidence": "what to cite from the resume, or an empty string"}}],
  "gaps_to_prepare": ["topics this role needs that the resume does not cover"],
  "questions_to_ask": ["two or three specific questions for the candidate to ask them"]}}

JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}
"""

# Behavioural interview questions (STAR), grounded in the resume the same way.
BEHAVIORAL_PREP_PROMPT = """You are preparing a candidate for the BEHAVIOURAL part of an interview for the role below, honestly.

Produce behavioural questions ("Tell me about a time...") that this role's competencies call for, and for each, which real situation from THIS candidate's resume would make the best STAR story.

HARD RULES
- Ground every "your_evidence" in a situation actually written in the resume: name the role/project it comes from and what they did there.
- If nothing in the resume fits a question, set "your_evidence" to "" and put the competency in gaps_to_prepare. Never invent a situation, conflict, team, result or number.
- 6 to 8 questions, covering the competencies the job description stresses (ownership, conflict, ambiguity, failure, influence, delivery under pressure...).

Return ONLY a valid JSON object:
{{"role_summary": "one line on which competencies this interview is really probing",
  "questions": [{{"question": "Tell me about a time...", "why": "the competency it tests", "your_evidence": "the resume situation to build the STAR answer on, or an empty string"}}],
  "gaps_to_prepare": ["competencies the resume gives no story for"],
  "questions_to_ask": ["two or three specific questions for the candidate to ask them"]}}

JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}
"""

# System design prompts sized to the role. Non-technical roles are told so,
# rather than handed design questions that will never be asked.
SYSTEM_DESIGN_PREP_PROMPT = """You are preparing a candidate for the SYSTEM DESIGN part of an interview for the role below, honestly.

First decide whether this role would realistically include a system design round (software, data, infrastructure, ML or similar engineering roles). If it would not, return {{"applicable": false, "role_summary": "one line saying why", "questions": [], "gaps_to_prepare": [], "questions_to_ask": []}}.

Otherwise produce 4 to 6 design prompts pitched at the seniority the job description implies, drawn from the domain the job description describes. For each, point at anything in THIS candidate's resume that gives them real material (systems they built, scale they handled, tools they used).

HARD RULES
- Ground every "your_evidence" in something actually written in the resume. If nothing relevant is there, set it to "" and put the topic in gaps_to_prepare. Never invent systems, scale or numbers.
- In "why", name the 2-3 concepts the prompt is really testing (e.g. idempotency, partitioning, caching, consistency trade-offs).

Return ONLY a valid JSON object:
{{"applicable": true,
  "role_summary": "one line on what the design round will probe",
  "questions": [{{"question": "Design ...", "why": "concepts it tests", "your_evidence": "resume material to draw on, or an empty string"}}],
  "gaps_to_prepare": ["design topics the resume gives no material for"],
  "questions_to_ask": ["two or three specific questions about their architecture to ask them"]}}

JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}
"""

# Rubric feedback on a practice answer. Every judgement must quote the answer
# itself; the server discards any quote that is not actually in the answer.
INTERVIEW_SCORE_PROMPT = """You are an interview coach giving rubric feedback on ONE practice answer. Be specific and fair; do not flatter.

QUESTION TYPE: {kind_label}
RUBRIC (score each 1-5): {rubric}

HARD RULES
- Judge ONLY what the answer actually says. For each rubric item, "quote" must be copied VERBATIM from the answer (a short phrase, max 25 words), or "" if the answer has nothing for that item.
- "fix" is one concrete improvement for that item. Never supply facts, numbers, employers or results the candidate did not give; where a number would help, say "add the number (e.g. [X%])".
- 1 = missing, 2 = weak, 3 = adequate, 4 = strong, 5 = excellent. An item with an empty quote scores 1 or 2.
- "stronger_outline" is a 3-5 step structure for a better answer built ONLY from what the candidate said plus bracketed placeholders for anything missing.

Return ONLY a valid JSON object:
{{"rubric": [{{"item": "rubric item name", "score": 1, "quote": "verbatim phrase or empty", "fix": "one concrete improvement"}}],
  "strengths": ["what genuinely works, max 3"],
  "biggest_gap": "the single most important thing to fix",
  "stronger_outline": ["step 1", "step 2", "step 3"]}}

QUESTION:
{question}

JOB CONTEXT (may be empty):
{job_description}

CANDIDATE'S ANSWER:
{answer}
"""

# A learning roadmap toward one target role, from the candidate's real resume.
# Projects exist to PROVE a missing skill; nothing claims results in advance.
ROADMAP_PROMPT = """You are a practical career coach. Build a learning roadmap that takes THIS candidate from their current resume to being a credible applicant for the target role.

TARGET ROLE: {target_role}
TIME AVAILABLE: {weeks} weeks at about {hours} hours per week

HARD RULES
- "strengths" are skills the resume ALREADY shows. For each, "evidence" must be copied verbatim from the resume (a short phrase). Never list a strength the resume does not show.
- Phases cover the GAPS between the resume and the target role, most important first. Their weeks must add up to {weeks}. Scope each phase to the hours available -- do not plan more than fits.
- Every phase ends with ONE portfolio project that proves its skills: something concrete to build, sized to the phase.
- "resume_line" is how the finished project could be described on a resume, with bracketed placeholders ([N users], [X ms]) for any result -- never a made-up number or outcome.
- Name concepts and skills to learn, not specific courses, websites or URLs.

Return ONLY a valid JSON object:
{{"summary": "one or two sentences on the gap between this resume and the target role",
  "strengths": [{{"skill": "...", "evidence": "verbatim phrase from the resume"}}],
  "phases": [{{"title": "...", "weeks": 2, "skills": ["..."], "learn": ["concept or topic"],
               "project": {{"name": "...", "build": "what to build, concretely", "proves": ["skill"], "resume_line": "..."}},
               "done_when": "an observable checkpoint"}}],
  "interview_topics": ["what interviews for this role will probe once the roadmap is done"]}}

CANDIDATE RESUME:
{resume_text}
"""

DIFF_PROMPT = """You are a professional resume editor. You have just rewritten a resume. Your task is to produce a JSON list of the specific improvements you made.

Return ONLY a JSON array of strings. Each string should be one clear, specific improvement that was made.
Focus on concrete changes like:
- "Added quantifiable metrics to 3 work experience bullet points"
- "Rewrote passive language to use strong action verbs (Led, Achieved, Delivered)"
- "Added a missing Professional Summary section"
- "Fixed ATS formatting issues: removed tables and graphics references"
- "Improved Clarity score by restructuring bullet points for readability"
- "Added 5 high-value ATS keywords from the target job description"

Original resume analysis weaknesses:
{weaknesses}

Instructions that were applied:
{instructions}

Return 5-8 specific improvement statements. Return ONLY the JSON array, nothing else."""
