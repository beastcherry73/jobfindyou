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
