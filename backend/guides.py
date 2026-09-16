"""Public guide content, served at /guides.

Plain data, authored by hand and rendered by templates/guides.html. Two rules
hold this content together, and both exist because the rest of the product is
held to them too:

  * Every number carries its source. Where a widely-quoted statistic turns out
    to have no source -- the "75% of resumes are rejected by the ATS" figure
    is the notorious one -- the guide says so rather than repeating it.
  * Examples are labelled as examples and use bracketed placeholders for any
    result. Nothing here is presented as a real person's outcome, because
    nothing here is one.

Adding a guide: append to GUIDES; /guides, the article route and the sitemap
pick it up automatically.
"""

SITE = "https://www.jobspike.in"

# One source list, referenced by id, so a figure cannot drift from its source.
SOURCES = {
    "ladders": {
        "label": "Ladders, \"Eye-Tracking Study\" (2018) — 30 recruiters, 10 weeks",
        "url": "https://www.theladders.com/static/images/basicSite/pdfs/TheLadders-EyeTracking-StudyC2.pdf",
    },
    "glassdoor": {
        "label": "Glassdoor, \"50 HR & Recruiting Stats\"",
        "url": "https://www.glassdoor.com/blog/50-hr-recruiting-stats-make-think/",
    },
    "nyc_pay": {
        "label": "NYC Commission on Human Rights, salary transparency law guidance",
        "url": "https://www.nyc.gov/site/cchr/media/pay-transparency.page",
    },
    "eu_pay": {
        "label": "EU Pay Transparency Directive 2023/970",
        "url": "https://eur-lex.europa.eu/eli/dir/2023/970/oj",
    },
}


def _g(slug, title, description, minutes, sections, sources=(), updated="2026-09-16"):
    return {"slug": slug, "title": title, "description": description, "minutes": minutes,
            "sections": sections, "sources": [SOURCES[s] for s in sources], "updated": updated}


GUIDES = [
    _g(
        "how-ats-really-reads-your-resume",
        "How an applicant tracking system really reads your resume",
        "What the software does and does not do, why the famous “75% are auto-rejected” figure has no source, and the formatting that actually costs you.",
        6,
        [
            {"h": "What the software actually is",
             "p": ["An applicant tracking system is a database. It stores applications, lets a recruiter search and filter them, and moves candidates through stages. Parsing your file into fields — name, employers, dates, skills — is one feature of that database, not a gatekeeper standing between you and a human.",
                   "That distinction matters because it changes what you should optimise. You are not trying to beat a robot. You are trying to make sure that when a person searches the database for “Python” and skims what comes back for a few seconds, your resume answers them."]},
            {"h": "The 75% claim, and why this site will not repeat it",
             "p": ["You will read everywhere that 75% of resumes are rejected by the ATS before a human sees them. The trail behind that number leads to a 2012 sales pitch by a company called Preptel, which sold resume-optimisation software and published no methodology, no sample and no survey. The company shut down the following year. The figure survived because it was repeated, not because it was ever measured.",
                   "The honest version is duller and more useful: most applications are read by someone, but that reading is fast and shallow, and it is fast and shallow for every application in the pile."]},
            {"h": "What is measured",
             "p": ["A 2018 eye-tracking study by Ladders fitted 30 recruiters with eye-tracking equipment and watched them review resumes over ten weeks. The average first pass lasted 7.4 seconds, and it followed a predictable path: current title and employer, previous title and employer, dates, then education.",
                   "Seven seconds is roughly the top third of the first page. Everything that decides whether you get a second look lives there."]},
            {"h": "Formatting that genuinely causes problems",
             "bullets": ["Text inside images or logos. Nothing can read it — not the parser, not the search.",
                         "Multi-column layouts and text boxes. Parsers read them in unpredictable order, so your job titles can arrive interleaved with your skills.",
                         "Headings the software does not recognise. “Where I’ve Worked” is charming; “Experience” is searchable.",
                         "Dates written only as “3 years”. Give a start and end month and year.",
                         "Critical detail in headers and footers, which some parsers drop entirely.",
                         "A PDF exported as a scan or photograph. If you cannot select the text, neither can anything else."]},
            {"h": "What to do instead",
             "p": ["Use one column, standard section headings, and a normal font. Put your title, your employer and your strongest evidence in the top third. Name the tools and skills the posting names, in the words the posting uses, wherever you can do so truthfully.",
                   "Then check it: upload it to JobSpike with the job description and see which of the role’s terms are actually on your resume and which are missing. That comparison is the whole point — not a magic score."]},
        ],
        sources=("ladders",)),

    _g(
        "resume-bullet-points-that-show-impact",
        "Writing resume bullet points that show impact",
        "The difference between listing duties and showing outcomes, and what to write when you genuinely have no numbers.",
        5,
        [
            {"h": "Most bullets describe the job, not the person",
             "p": ["“Responsible for maintaining the reporting pipeline” describes a job that existed. Anyone holding that title could have written it. It tells a reader nothing about you, and it competes with a hundred identical lines.",
                   "A useful bullet has three parts: what you did, how you did it, and what changed as a result."]},
            {"h": "A shape that works",
             "p": ["Action verb → the specific thing → the method or tool → the outcome. For example (illustrative, not a real person): “Rebuilt the nightly reporting job in Python, replacing a full-table scan with an indexed query, cutting runtime from [40] minutes to [6].”",
                   "Note the brackets. If you do not know the exact figures, write the placeholder and go and find them before you send the resume. Inventing a number is the one move that can end an interview badly, because a good interviewer will ask how you measured it."]},
            {"h": "When you truly have no numbers",
             "p": ["Plenty of real work has no metric attached, especially early in a career. Scope and consequence still work: how many people used the thing, how often it ran, what it replaced, what stopped going wrong, who else adopted it.",
                   "“Wrote the onboarding guide the three new joiners now follow” is concrete without claiming a percentage."]},
            {"h": "Words to drop",
             "bullets": ["“Responsible for” — name the action instead.",
                         "“Helped with” — say what your part was.",
                         "“Various”, “numerous”, “multiple” — give the number.",
                         "“Results-driven team player” and its relatives — adjectives about yourself carry no information.",
                         "Tool lists with no verb — “Python, SQL, AWS” belongs in the skills section, not in a bullet."]},
        ]),

    _g(
        "tailoring-a-resume-to-a-job-description",
        "Tailoring a resume to a job description without keyword stuffing",
        "How to read a posting for what it is really asking, and where tailoring stops being honest.",
        5,
        [
            {"h": "Read the posting twice",
             "p": ["First pass: mark every noun that is a skill, a tool, a domain or a responsibility. Second pass: mark which of those appear more than once, or appear in the first three bullets. Postings repeat what actually matters, usually because several people wrote them and the important parts survived every draft.",
                   "The repeated items are what the resume must answer. The rest is wish-list."]},
            {"h": "Match the posting’s words to your own experience",
             "p": ["If the posting says “ETL pipelines” and you built “data ingestion jobs”, and they are the same thing, use their phrase. That is not dishonest; it is translation, and the person searching the database is searching for their phrase.",
                   "If the posting asks for something you have never done, say nothing about it on the resume. Prepare an honest answer for the interview instead: the nearest thing you have done, and how quickly you picked up the last comparable tool."]},
            {"h": "Where the line is",
             "bullets": ["Reordering bullets so the relevant ones come first — fine.",
                         "Renaming a technology to the posting’s word for the same technology — fine.",
                         "Adding a skill you used once, listed alongside skills you use daily — risky; separate them.",
                         "Adding a skill you have never used — not fine. It surfaces in the first technical question."]},
            {"h": "Keyword stuffing does not work anyway",
             "p": ["A block of keywords in white text, or a “skills” list of forty tools, does not fool a search and does annoy a reader. Recruiters filter by a handful of terms and then read; an implausible list makes the reading go worse, not better.",
                   "JobSpike’s match view exists for this: it shows which of the role’s terms are on your resume and which are not, so you can add the ones you can honestly back up and prepare for the ones you cannot."]},
        ]),

    _g(
        "star-answers-for-behavioural-interviews",
        "Answering behavioural questions with STAR",
        "The four parts, the one most people skip, and how to prepare stories without scripting them.",
        6,
        [
            {"h": "What the question is for",
             "p": ["“Tell me about a time…” is an attempt to replace opinion with evidence. Anyone can say they handle conflict well. The interviewer wants one occasion, with enough detail that they can picture it and ask follow-ups.",
                   "So the answer has to be a specific episode, not a policy statement about how you generally behave."]},
            {"h": "The four parts",
             "bullets": ["Situation — where, when, and what was going wrong. Two sentences.",
                         "Task — what you specifically were responsible for. One sentence.",
                         "Action — what you did, step by step, in the first person. This is most of the answer.",
                         "Result — what changed, with a number where one exists, and what happened afterwards."]},
            {"h": "The part people skip",
             "p": ["Result. Answers tend to trail off after the action, because the action is the interesting part to the person who lived it. The interviewer has no way to judge the action without knowing how it turned out — including when it turned out badly.",
                   "A failure with a clear result and a lesson beats a success with no result at all."]},
            {"h": "Say “I”",
             "p": ["“We migrated the database” tells the interviewer that a team did something. They are not interviewing the team. Describe what the team did in one sentence, then switch to what you did inside it."]},
            {"h": "Preparing without scripting",
             "p": ["Write six episodes from your own history: a failure, a conflict, an ambiguous problem, something you shipped under pressure, something you improved without being asked, and something you learned fast. Most behavioural questions map onto one of those six.",
                   "Do not memorise wording. Memorise the facts — dates, numbers, who was involved — so you can tell each one in whatever order the question demands. JobSpike’s interview practice will score a written answer against these four parts and quote the words you actually used."]},
        ]),

    _g(
        "fresher-resume-india",
        "A first resume with no work experience",
        "What to put on the page when you have never had a job, written for students and recent graduates.",
        6,
        [
            {"h": "The page is not empty",
             "p": ["Without employment, the material is coursework, projects, competitions, volunteering, freelance or family-business work, campus roles and anything you have built. These are real evidence; they are simply filed under different headings.",
                   "What they need is the same treatment as a job: what you did, how, and what came of it."]},
            {"h": "Order for a first resume",
             "bullets": ["Name and contact details, including a link to code or portfolio work if you have any.",
                         "A one-line summary naming the role you want. “Final-year CS student looking for a backend engineering internship.”",
                         "Education, with the degree, institution, year, and marks only if they help you.",
                         "Projects — the longest section, two to four of them, strongest first.",
                         "Skills, split into what you have used seriously and what you have only touched.",
                         "Positions of responsibility, volunteering, competitions."]},
            {"h": "Write projects like work",
             "p": ["A project entry should say what it does, what you built it with, and one fact about its scale or outcome: how many people used it, what it processes, what it replaced, what you measured. (Illustrative: “Attendance tracker used by [N] students in my department; cut manual roll-call to under a minute.”)",
                   "A university assignment everyone in the class submitted is worth one line. Something you built because you wanted it to exist is worth four."]},
            {"h": "Things that cost freshers interviews",
             "bullets": ["A photograph, date of birth, marital status or father’s name. Common on Indian templates, unnecessary, and in several countries actively unhelpful.",
                         "Listing every technology from every syllabus. A reader assumes you can discuss anything you list.",
                         "“Seeking a challenging position in a reputed organisation…” objectives. Name the role instead.",
                         "Two pages. One is enough, and it forces you to choose."]},
        ]),

    _g(
        "salary-ranges-in-job-postings",
        "How to read the salary range in a job posting",
        "Where posted ranges come from, what they leave out, and how to use them without over-reading them.",
        5,
        [
            {"h": "Why ranges appear at all",
             "p": ["Pay transparency laws are the reason a range is on the page. New York City, Colorado, California, Washington and others require employers to publish a good-faith range for roles they advertise, and the EU Pay Transparency Directive extends similar duties across member states as it is transposed into national law.",
                   "That is also why coverage is uneven. A US or EU posting may carry a range while an identical role elsewhere carries none, and that difference says nothing about the pay."]},
            {"h": "What the number is, and is not",
             "bullets": ["It is usually base salary only. Bonus, equity and commission sit outside it unless the posting says otherwise — look for “OTE”, which folds commission in.",
                         "It is a range for the level, not an offer. Most hires land in the middle, not at the top.",
                         "Multi-location postings often list several ranges by zone. The highest is normally the most expensive city, not the one you would be hired into.",
                         "A very wide range usually means the posting covers more than one level."]},
            {"h": "Using it",
             "p": ["Compare the range against several live postings for the same title and level, in the same country, rather than against one. JobSpike’s Salaries page does exactly that, using only ranges employers published in their own live postings and counting each company once — and it declines to show a median when too few companies have published.",
                   "Treat all of it as evidence about what employers are advertising, not as a measurement of what people are actually paid."]},
        ],
        sources=("nyc_pay", "eu_pay")),
]

GUIDES_BY_SLUG = {g["slug"]: g for g in GUIDES}
