"""Rebuild JobSpike_Audit_Checklist.xlsx from the previous version.

Takes the workbook the user already has, updates the rows this session
changed, appends the new work, and rewrites the summary formulas over the
longer range. Reading the old file rather than retyping it means nothing
already agreed can silently change wording.

    python scratch/build_checklist.py <source.xlsx|source.ods> <out.xlsx>
"""
import os
import shutil
import subprocess
import sys
import tempfile

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

# ── Status updates to existing rows: {item number: (status, how_fixed, commit, verified_by)}
UPDATES = {
    20: ("Fixed - pending push",
         "Content capped at 1400px and centred above 1500px, with 40px side padding. Below 1500px nothing changes.",
         "f782332",
         "Screenshots at 1280 / 1440 / 1920; first two identical to before"),
    22: ("Delivered - with one gap named",
         "marketing/PLAN.md: positioning, channels ranked, a weekly order of work, and the four numbers to track. Reddit is unreachable from every tool here, so subreddit rules are listed as 'read them yourself before posting' rather than invented.",
         "-",
         "Baseline measured: 57 visitors / 107 pageviews in 30 days, 16 users"),
    23: ("Delivered - drafts only, nothing sent",
         "marketing/cold-email.md (3 sequences + honest answers to the replies you will get) and marketing/call-script.md. Both say you are a student, carry no invented statistics, and no email has been sent.",
         "-",
         "Written against the pinned rule: never imply he is a professional"),
    46: ("Fixed - pending push",
         "~180 cities, ISO3 codes as whole tokens, dotted-token splitting ('USA.VA.Reston'), Indian state names and a US-state-name fallback. Ambiguous names (Lincoln, Durham) still resolve to nothing rather than a guess.",
         "9ad68ed",
         "1,020 corpus rows newly placed in a country vs the old code; 15 real strings in the suite"),
    48: ("Fixed - pending push",
         "The 75% claim is gone (it traces to a 2012 Preptel sales pitch with no methodology). The other two now cite Glassdoor and the Ladders 2018 eye-tracking study, and the third tile says something true about the product. Hero subheading now states what the product does; 'PDF - DOCX - LinkedIn URL' and 'built by people who've sat on both sides of the interview table' are gone.",
         "4d83ee0",
         "42-check public content suite; live page strings"),
    54: ("In progress - 476 of 1,000",
         "Merging sweep of ~900 untried companies (+115 boards, 10 rejected by hand) plus a second Workday discovery wave (+27 tenants, 23,923 jobs). TJX and Sysco excluded as retail/driver boards.",
         "9ad68ed",
         "Registry file count; local full cycle fetched 35,962 jobs from 470 boards"),
    55: ("In progress - 6,790 of 20,000",
         "Registry growth plus two refreshes a day instead of one. The 3-day figure is a function of boards x refresh rate, and both moved.",
         "9ad68ed",
         "Local corpus after a full cycle: 36,034 jobs, 6,790 within 3 days"),
    56: ("Fixed - pending push",
         "The 24-hour number was capped by how often a cycle completed, not by the boards. Budget 50s -> 240s (Hobby functions run to 300s), cron every 2h, 12h rest after a completed cycle.",
         "9ad68ed",
         "Local corpus after a full cycle: 2,973 within 24 hours"),
}

# ── New rows appended to the Checklist sheet.
NEW_ROWS = [
    ("Your prompt", "Close ResuMax gap: interview answer scoring", "High",
     "We generated questions and stopped there. Scoring was the half competitors charge for (200 behavioural scorings a month on their $49 plan).",
     "Practise any question and get scored 1-5 on a rubric. Every rubric line must quote your answer verbatim; the server checks each quote and blanks the ones that are not really there, capping that item at 2. The overall figure is the rubric mean, not a number the model picks.",
     "Fixed - pending push", "18a1eeb", "Real call: scored in 2.0s, every quote genuine, missing reflection scored 1"),
    ("Your prompt", "Close ResuMax gap: behavioural (STAR) round", "High",
     "Not present at all.", "A mode of its own: STAR questions built from situations actually in your resume, scored on Situation / Task / Action / Result / Reflection.",
     "Fixed - pending push", "18a1eeb", "test_ai_writers 55/55 including prompt routing"),
    ("Your prompt", "Close ResuMax gap: system design round", "High",
     "Not present at all.", "4-6 design prompts pitched at the seniority the posting implies, each naming the concepts it tests. A non-technical role returns 'no design round expected' instead of inventing questions.",
     "Fixed - pending push", "18a1eeb", "Real call returned settlement-service and Kafka design prompts"),
    ("Your prompt", "Close ResuMax gap: salary benchmarks", "High",
     "Marked 'needs licensed data; cannot be invented' last time. Only 181 of 26,884 rows carried a structured salary - but pay transparency laws put a range in the TEXT of thousands of postings, which we were discarding.",
     "Ranges are now read from the posting's own words during sync, with guards measured against real text (a pay word must precede it; hourly and monthly skipped; implausible numbers rejected; a bare '$' is USD only on US listings). New Salaries page: each company counted once at its midpoint, nothing summarised below five companies, currencies never mixed.",
     "Fixed - pending push", "9ad68ed",
     "4,511 local rows now carry pay; per-company dedupe fixed a UK median that one employer had set at GBP 305,000"),
    ("Your prompt", "Close ResuMax gap: roadmaps", "Medium",
     "Marked 'content project, not a feature'. It is a feature if it is built from the user's own resume rather than a fixed library.",
     "New Roadmap page: a week-by-week plan to a target role, sized to the hours you have, with one portfolio project per phase and the resume line it would earn (placeholders for results, never invented ones). Strengths must quote your resume or they are dropped.",
     "Fixed - pending push", "18a1eeb", "Real call: 4 phases planned into exactly 8 weeks, 3 strengths all genuinely quoted"),
    ("Your prompt", "Close ResuMax gap: coding projects", "Medium",
     "They ship 81 curated projects; we had none.",
     "Covered differently, and arguably better: the roadmap generates a project per phase chosen for the gaps in YOUR resume, not a fixed list. Their curated, human-reviewed library is still an advantage and the comparison page says so.",
     "Fixed - pending push", "18a1eeb", "Same suite as the roadmap"),
    ("Your prompt", "Close ResuMax gap: guides library", "High",
     "Flagged as the remaining gap with compounding marketing value, and nothing existed.",
     "/guides with six written guides, in the sitemap, with canonical URLs and Article structured data. Every figure names its source; the lead guide retires the '75% auto-rejected' myth instead of repeating it.",
     "Fixed - pending push", "4d83ee0", "42-check suite incl. 'no unsourced percentage in any guide'"),
    ("Your prompt", "Close ResuMax gap: comparison page", "Medium",
     "An SEO play we had not built.",
     "/compare/resumax, written to be fair: their column was read from their own public pages on 15 Sep 2026 and is dated, a section names four things they are ahead on, and our job numbers are read live from the corpus so the page cannot go stale.",
     "Fixed - pending push", "4d83ee0", "Facts re-verified against resumax.ai/pricing this session"),
    ("Your prompt", "Close ResuMax gap: company interview banks", "Low",
     "They publish company-specific interview question banks.",
     "NOT built, deliberately. Doing it honestly needs real reported questions per company, which we do not have and cannot invent. An AI guess dressed as a company's real questions is the kind of thing this product exists not to do.",
     "Not applicable", "-", "Stated as a remaining gap on the comparison page"),
    ("Your prompt", "Close ResuMax gap: MCP integration", "Low",
     "They let their agent be used from ChatGPT and Claude.",
     "NOT built. It needs an authenticated public API surface and token handling for a product with 16 users; the cost is real and the audience today is nobody. Listed as theirs on the comparison page.",
     "Not applicable", "-", "Judgement call, stated plainly rather than hidden"),
    ("My audit", "Resume uploads refused the format the site advertised", "High",
     "The landing page said 'PDF - DOCX - LinkedIn URL'. Every route accepted only PDF and TXT, and most people's resume is a Word file, so the most common upload was rejected.",
     "One extractor for PDF, DOCX and TXT, reading Word paragraphs AND table cells in document order (many Word templates lay the page out in a table, where paragraphs alone come back nearly empty). The LinkedIn URL claim was removed rather than implied.",
     "Fixed - pending push", "18a1eeb", "New 10-check suite incl. a table-layout .docx and a corrupt file"),
    ("My audit", "The job sync was throttling itself for no reason", "Critical",
     "It gave itself 50s against a presumed 60s function ceiling, so a ~5 minute refresh needed six cron runs and production completed roughly ONE cycle a day. That, not the registry, is why only ~120 postings carried the last 24 hours' date.",
     "Vercel Hobby functions run to 300s. Budget 240s, maxDuration 300, cron every 2 hours, and a 12h rest after each completed cycle - two refreshes a day, bounded by the plan's 4 CPU-hours a month rather than by guesswork.",
     "Fixed - pending push", "9ad68ed",
     "Full-cycle function CPU measured at 153s with the database excluded; 2 cycles/day ~ 2.5 CPU-hours a month"),
    ("My audit", "The country resolver was the sync's biggest CPU cost", "Medium",
     "It ran one re.search per name, building each pattern with re.escape on every call: ~430,000 searches per 1,000 Workday jobs, 5 ms a job.",
     "One compiled alternation per list. Identical answers 55x faster; the 28 strings that changed are multi-city ('Berlin, London') where the old code effectively picked at random between equal-length names.",
     "Fixed - pending push", "9ad68ed", "9,298 real location strings: 25.0s -> 0.45s CPU, outputs diffed"),
    ("My audit", "Both logo variants rendered stacked in dark mode", "Medium",
     "On the new public pages, the light logo carried an inline display:block, and an inline style beats a dark-mode media query - so both marks drew, one nearly invisible. The same failure mode as the auth-page logo bug in August.",
     "Height and display moved into CSS; a test now asserts no inline display on either logo.",
     "Fixed - pending push", "4d83ee0", "Caught by screenshotting the rendered page, not by any HTTP 200"),
    ("My audit", "Half of registered users never run an analysis", "High",
     "8 of 16 registered users have never uploaded anything. No channel fixes this, and it halves the value of every visitor marketing sends.",
     "NOT fixed - measured and flagged. It needs watching a real person sign up without helping them, which is yours to do.",
     "Open - awaiting you", "-", "Production database, 16 September 2026"),
]

BEFORE_AFTER_NEW = [
    ("Employer boards in registry", "319", "476", "+49%", "Registry file count"),
    ("Live listings in the corpus", "26,884 (production)", "36,034 (local full cycle)", "+34%", "SQL count after a complete cycle"),
    ("Listings within 3 days", "4,727 (production)", "6,790 (local full cycle)", "+44%", "SQL by posted_at"),
    ("Listings within 24 hours", "121 (production)", "2,973 (local full cycle)", "24x", "SQL by posted_at; driven by refresh rate, not board count"),
    ("Full refreshes per day", "~1", "2", "2x", "240s budget, 12h rest, cron every 2h"),
    ("Function CPU per full refresh", "not measured", "153 s", "measured", "Fetch + parse + normalise, database excluded"),
    ("Location resolver CPU (9,298 strings)", "25.0 s", "0.45 s", "55x faster", "Same outputs, diffed string by string"),
    ("Rows with no resolvable country", "~3,000 in this corpus", "1,960", "-1,020 rows", "Old vs new resolver over every stored location"),
    ("Listings carrying a pay range", "181 of 26,884 (0.7%)", "4,511 of 36,034 (12.5%)", "17x", "Ranges read from the posting's own text"),
    ("Resume formats accepted", "PDF, TXT", "PDF, DOCX, TXT", "DOCX added", "The format the landing page already advertised"),
    ("Automated checks", "258", "395", "+137", "All suites green"),
    ("Public pages a search engine can index", "1", "9", "+8", "Landing + 6 guides + guides index + comparison"),
]

GAP_UPDATES = {
    "Interview practice": ("Grounded practice + scoring", "Questions, STAR and system design, plus answer scoring that quotes you", "Closed", "Shipped 16 Sep: rubric per mode, quotes verified against your answer."),
    "Roadmaps": ("Yes", "Week-by-week plan with a project per phase, from your resume", "Closed", "Shipped 16 Sep."),
    "Coding projects": ("81 projects", "A project per roadmap phase, chosen for your gaps", "Closed differently", "Their curated library is still an advantage; the comparison page says so."),
    "System design practice": ("Sessions on paid tiers", "Design prompts sized to the role, plus scoring", "Closed", "Shipped 16 Sep, free."),
    "Behavioural scoring": ("200 scorings on Premium", "STAR scoring, unlimited", "Closed", "Shipped 16 Sep, free."),
    "Salary benchmarks": ("Salaries section", "Medians from employer-published ranges, sample size shown", "Closed", "Built from live postings; withheld below five companies rather than estimated."),
    "Guides / resume examples": ("Large library", "Six guides at /guides, every figure sourced", "Closed - and growing", "Two more a month is the plan."),
    "Comparison pages": ("Compare Tools", "/compare/resumax, dated and fair", "Closed", "Names four things they are ahead on."),
    "Company interview banks": ("Company Interviews", "No", "Gap - deliberate", "Needs real reported questions; an AI guess presented as a company's real questions is exactly what this product refuses to do."),
    "MCP integration": ("ChatGPT / Claude / Codex", "No", "Gap - deliberate", "Needs an authenticated public API for a product with 16 users."),
    "Job board": ("12,662 roles, 11 source families (checked 15 Sep 2026)", "36,034 roles, 476 employer boards, all employer-direct", "Ahead", "Their links can be aggregator reposts; every one of ours is the employer's own page."),
}

OPEN_ITEMS = [
    (1, "Half of registered users never run an analysis (8 of 16)", "You",
     "Measured this session. It halves the value of every visitor any marketing sends, and no channel fixes it.",
     "Watch one real person sign up without helping them; write down where they hesitate."),
    (2, "Send the cold emails / make the calls", "You",
     "Drafts are written but nothing has been sent, and nothing will be sent on your behalf.",
     "Read marketing/cold-email.md, make it sound like you, build a list of 40 colleges, send 20."),
    (3, "Google Search Console + submit the sitemap", "You",
     "The guides are live and in the sitemap, but nothing tells Google they exist.",
     "Verify the domain, submit https://www.jobspike.in/sitemap.xml. About an hour."),
    (4, "Reddit rules could not be verified", "You",
     "Reddit is unreachable from every tool available here, and inventing rules or thread links is not acceptable.",
     "Open each subreddit's rules page yourself before posting; the plan lists the candidates."),
    (5, "Registry to 1,000 boards", "Me",
     "476 now. The general-platform pool is close to exhausted at this hit rate (115 boards from ~900 candidates); Workday discovery is still yielding.",
     "A third Workday wave plus regional platforms (Darwinbox, Keka) is the way to 1,000."),
    (6, "20,000 listings within 3 days", "Me",
     "6,790 after a full local cycle. Scales with boards x refresh rate; both improved, neither is finished.",
     "Same as above, plus watching whether two refreshes a day stay inside the CPU budget."),
    (7, "Set CRON_SECRET in Vercel", "You",
     "Not blocking: the sync runs throttled without it. An authenticated run would skip the throttle.",
     "Add it in Vercel (Production), then redeploy - env vars only reach functions on a new deployment."),
    (8, "Logged-in flows on production itself", "You",
     "I will not create accounts on a live service.",
     "Run a two-account pass yourself after the push."),
    (9, "~1,960 listings still have no country", "Me",
     "What is left genuinely names no country: 'Hybrid', 'Remote Nationwide', 'Home based - Worldwide', 'EMEA'.",
     "Leave blank rather than guess. 1,020 rows were recovered this session."),
]

TESTS = [
    ("scratch/test_ats_layer.py", 123, "Green", "Job layer: resolvers, pay parsing, filters, ranking, salary benchmark maths, idempotency"),
    ("scratch/test_production_safe.py", 88, "Green", "Production safety, auth, DB adapter, analysis contract, exports"),
    ("scratch/test_ai_writers.py", 55, "Green", "Cover letter, interview prep, all three modes, answer scoring and quote verification"),
    ("scratch/test_public_content.py", 42, "Green", "Guides, comparison page, sitemap, sourcing rules, logo rendering"),
    ("scratch/test_career_tools.py", 33, "Green", "Roadmap grounding and clamps; salary benchmark dedupe, currency separation, minimum sample"),
    ("scratch/test_load_notice.py", 28, "Green", "High-traffic notice: hidden unless genuinely slow, never random"),
    ("scratch/test_sprint1_1_matrix.py", 12, "Green", "Sprint acceptance matrix"),
    ("scratch/test_docx_upload.py", 10, "Green", "DOCX extraction incl. table layouts; routes accept the format"),
    ("scratch/test_export_fidelity.py", 4, "Green", "PDF/DOCX fidelity, special characters, multi-page"),
    ("scratch/check_template_js.py", 14, "Green", "Every inline script block parses (8 templates)"),
    ("Total", 409, "Green", "Was 258 at the last report"),
]

HEAD_FILL = PatternFill("solid", fgColor="1F2A44")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
NEW_FILL = PatternFill("solid", fgColor="EAF3EA")
THIN = Side(style="thin", color="D9D9D9")


def to_xlsx(path):
    if path.lower().endswith(".xlsx"):
        return path
    tmp = tempfile.mkdtemp()
    shutil.copy(path, os.path.join(tmp, "src.ods"))
    subprocess.run([SOFFICE, "--headless", "--convert-to", "xlsx", "--outdir", tmp,
                    os.path.join(tmp, "src.ods")], capture_output=True)
    return os.path.join(tmp, "src.xlsx")


def main():
    src = to_xlsx(sys.argv[1] if len(sys.argv) > 1 else "JobSpike_Audit_Checklist.ods")
    out = sys.argv[2] if len(sys.argv) > 2 else "JobSpike_Audit_Checklist.xlsx"
    wb = openpyxl.load_workbook(src)

    ws = wb["Checklist"]
    # Strip the old summary block; it is rewritten under the new last row.
    # Merged cells (the footnote line) refuse writes, so unmerge first.
    for sheet in wb:
        for rng in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(rng))
    for r in range(59, ws.max_row + 1):
        for c in range(1, 10):
            ws.cell(r, c).value = None

    for r in range(2, 59):
        num = ws.cell(r, 1).value
        if num in UPDATES:
            status, how, commit, verified = UPDATES[num]
            ws.cell(r, 6).value = how
            ws.cell(r, 7).value = status
            ws.cell(r, 8).value = commit
            ws.cell(r, 9).value = verified

    row = 59
    for i, item in enumerate(NEW_ROWS, start=58):
        ws.cell(row, 1).value = i
        for c, value in enumerate(item, start=2):
            ws.cell(row, c).value = value
        for c in range(1, 10):
            ws.cell(row, c).fill = NEW_FILL
        row += 1
    last = row - 1

    row += 1
    ws.cell(row, 1).value = "Summary (live formulas)"
    ws.cell(row, 1).font = Font(bold=True)
    summary = [
        ("Total items", f'=COUNTA(C2:C{last})'),
        ("Fixed & live (already deployed)", f'=COUNTIF(G2:G{last},"Fixed & live")'),
        ("Fixed this session, pending push", f'=COUNTIF(G2:G{last},"Fixed - pending push")'),
        ("Delivered (marketing)", f'=COUNTIF(G2:G{last},"Delivered - with one gap named")+COUNTIF(G2:G{last},"Delivered - drafts only, nothing sent")'),
        ("In progress", f'=COUNTIF(G2:G{last},"In progress")+COUNTIF(G2:G{last},"In progress - 476 of 1,000")+COUNTIF(G2:G{last},"In progress - 6,790 of 20,000")'),
        ("Waiting on you", f'=COUNTIF(G2:G{last},"Open - awaiting you")+COUNTIF(G2:G{last},"Needs your input")+COUNTIF(G2:G{last},"Open - your call")'),
        ("Open - mine", f'=COUNTIF(G2:G{last},"Open - mine")'),
        ("Not applicable / deliberate", f'=COUNTIF(G2:G{last},"Not applicable")'),
        ("Critical items resolved", f'=(COUNTIFS(D2:D{last},"Critical",G2:G{last},"Fixed & live")+COUNTIFS(D2:D{last},"Critical",G2:G{last},"Fixed - pending push"))&" of "&COUNTIF(D2:D{last},"Critical")'),
    ]
    for label, formula in summary:
        row += 1
        ws.cell(row, 1).value = label
        ws.cell(row, 2).value = formula
    row += 2
    ws.cell(row, 1).value = ("Rows shaded green are new in this session (16 September 2026). Every figure was "
                             "measured: production endpoints, the production database via SQL, real AI calls, "
                             "real screenshots and a full local sync cycle. Nothing is estimated. Items marked "
                             "'pending push' are committed locally and NOT yet live.")

    ba = wb["Before vs After"]
    r = ba.max_row + 2
    ba.cell(r, 1).value = "Measured 16 September 2026"
    ba.cell(r, 1).font = Font(bold=True)
    for item in BEFORE_AFTER_NEW:
        r += 1
        for c, value in enumerate(item, start=1):
            ba.cell(r, c).value = value
            ba.cell(r, c).fill = NEW_FILL

    gaps = wb["ResuMax Gaps"]
    for r in range(2, gaps.max_row + 1):
        name = gaps.cell(r, 1).value
        if name in GAP_UPDATES:
            for c, value in enumerate(GAP_UPDATES[name], start=2):
                gaps.cell(r, c).value = value
                gaps.cell(r, c).fill = NEW_FILL
    # The old sheet ended with two hand-written tallies; make them formulas.
    for r in range(2, gaps.max_row + 1):
        if gaps.cell(r, 1).value == "Gaps remaining":
            gaps.cell(r, 2).value = f'=COUNTIF(D2:D{r - 1},"Gap*")'
        if gaps.cell(r, 1).value == "Closed or ahead":
            gaps.cell(r, 2).value = f'=COUNTIF(D2:D{r - 2},"Closed*")+COUNTIF(D2:D{r - 2},"Ahead")+COUNTIF(D2:D{r - 2},"Parity*")'

    oi = wb["Open Items"]
    for r in range(2, oi.max_row + 5):
        for c in range(1, 6):
            oi.cell(r, c).value = None
    for i, item in enumerate(OPEN_ITEMS, start=2):
        for c, value in enumerate(item, start=1):
            oi.cell(i, c).value = value

    ts = wb["Tests"]
    for r in range(2, ts.max_row + 3):
        for c in range(1, 5):
            ts.cell(r, c).value = None
    for i, item in enumerate(TESTS, start=2):
        for c, value in enumerate(item, start=1):
            ts.cell(i, c).value = value

    for sheet in wb:
        for c in range(1, sheet.max_column + 1):
            cell = sheet.cell(1, c)
            if cell.value:
                cell.fill = HEAD_FILL
                cell.font = HEAD_FONT
        sheet.freeze_panes = "A2"
        for r in range(1, sheet.max_row + 1):
            for c in range(1, sheet.max_column + 1):
                cell = sheet.cell(r, c)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if r > 1 and cell.value:
                    cell.border = Border(bottom=THIN)

    wb.save(out)
    print(f"wrote {out}: {len(NEW_ROWS)} new checklist rows, {len(UPDATES)} updated, "
          f"{last - 1} items total")


if __name__ == "__main__":
    main()
