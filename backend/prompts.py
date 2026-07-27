ANALYSIS_PROMPT = """You are an elite executive tech recruiter and ATS optimization director. Perform a rigorous, multi-dimension analysis of the candidate's resume and return ONLY a valid JSON object.

Keys required in JSON response:
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

{job_context}

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

SAFE_OPTIMIZE_PROMPT = """You are an elite executive resume writer and ATS optimization specialist. 
Your goal is to optimize the resume below for maximum ATS compatibility, grammar, and professional polish.

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

STRICT RULES:
- Elevate vocabulary to executive C-suite / VP / Senior Director level.
- DO NOT invent fake facts, metrics, or false accomplishments.
- Preserve every technology, award, company name, and certification.
- Output clean Markdown only.

{instructions_context}

Original Resume:
{resume_text}"""

IMPROVE_PROMPT = SAFE_OPTIMIZE_PROMPT

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
