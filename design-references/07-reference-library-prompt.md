# JobSpike — Full Reference Library + Build Prompt (for Opus 4.8)

Paste the block below into a fresh Opus 4.8 session. It leads with the skill
command stack, then the complete reference library with a takeaway for every
site, then the task.

---

```
ROLE: You are the design lead for JobSpike, an AI Career Operating System
(jobspike.in). Design/enhance an authenticated screen (or the marketing landing)
to $10,000-agency quality in the fixed Direction C identity. Preview only —
never touch workspace.html, index.html, backend/, or the database.

================= STEP 1 — INVOKE THE SKILL STACK (in order) =================
/frontend-design      (aesthetic direction; avoid AI-generated defaults)
/ui-ux-pro-max        (patterns, palettes, UX rules, chart specs — search tool)
/dataviz              (score rings, bars, funnels, the Career Signal, timelines)
/artifact-design      (theming + delivery — invoke LAST, before writing the file)
Higgsfield is NOT in the stack (wrong tool for the app; excluded per doctrine).

Run this ui-ux-pro-max command stack and synthesize the results (Windows path;
use python / python3 / py -3):
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "career resume SaaS professional dashboard calm premium" --design-system -f markdown
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "dashboard information hierarchy one focal point" --domain ux
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "muted categorical palette data visualization accessible" --domain color
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "application funnel pipeline progress" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "north star composite index score vs target bullet" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "skill gap match coverage proportion keyword" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "empty state first run onboarding" --domain ux
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "editorial storytelling landing hero product demo premium" --domain landing

================= STEP 2 — READ (binding) =================
All of design-references/ (00–07) + inspirations/. CLAUDE.md for product + stack
(Flask + server-rendered templates + vanilla JS + custom CSS + Chart.js; NEVER
React/Tailwind/shadcn). The current previews in previews/ (build on them).

================= STEP 3 — THE REFERENCE LIBRARY (takeaway per site) =========

— OWN PRODUCT (north star; extend, don't replace) —
* jobspike.in (marketing, LIVE): warm ivory + Inter/Instrument Serif/JetBrains
  Mono + cobalt; editorial narrative, REAL product UI as hero, ATS 61->93 proof,
  one dark reveal band + one cobalt CTA band. KEEP all of it. AVOID its tells:
  the "CHAPTER 0X" chrome and the repeated adjective "quiet".
* jobspike.in (app dashboard, LIVE — the current build): 92% resume-health ring
  with word "Excellent" + "+7 since first scan"; "Today's Priority" card;
  Resume Confidence as a WORD ("High"); Interview Readiness ring (87%); Score
  Trajectory as a row of colored scan dots (92/72/0/20); "AI Coach — Action Plan"
  checklist. KEEP: score+word pairing, the trajectory dots, dual rings (health +
  interview readiness), the coach action-plan checklist. This is the screen to
  match and extend.

— REFERO PICKS (concrete DESIGN.md on styles.refero.design) —
* Linear: calm app-shell restraint, accent ~5% of pixels, near-zero decoration.
* Mercury: ONE accent for ONE action; separate surfaces by a one-step value lift,
  NOT drop shadows; headings at medium weight (never 700); hero-metric framing.
* Dub: 1px hairline borders (not shadows); one committed action color; radius
  vocabulary pill/12/8; tidy rows + understated area charts; product-UI imagery.
* Origin: three-voice type (serif=emotion, sans=UI, mono=data); honest-but-warm
  progress/milestone tone.
* Relate: single blue for pipeline-active dots; the stage spine; green/amber/
  coral as SUPPORTING status only, never a second brand color.

— SCREENSHOTS REVIEWED —
* Flux (health dashboard): REJECT the neon-lime + purple palette (wellness signal,
  wrong for career-tech). KEEP promoting ONE metric card via colour inversion.
* BizLink (CRM): KEEP the kanban + card-expands-to-detail (no modal) + compact
  KPI strip. REJECT the moody dark-agency mood.

— SITES REVIEWED —
* tsenta.com (YC): KEEP the "transparent agent" receipt (+/- diffs, staged
  workflow labels) -> our Improve receipt. Trust through visibility.
* lineaprompt.com: KEEP the audit-trail + version-diff "Time Machine" and the
  upfront trust/privacy note -> Builder versions + upload trust line.
* resumax.ai: SCOPE reference only (scoring, rewrite, job matching, interview
  prep, cover letters) — NOT a visual one. NOTE: resumax.COM is a parked GoDaddy
  "for sale" page, not the product. Warning: don't let its scope creep in.
* noth.in: REJECT for the app (creative-portfolio bounce motion; marketing-only).
* serotoninn.com: REJECT the literal gothic-fashion look. KEEP the principle:
  constraint breeds personality (limit palette/type so every choice works harder).
* madewithgsap.com: confirms the marketing funnel order is sound; no app change.
* dock.cool: widget / multi-profile customization = a FUTURE personalization idea.
* rocketweblabs.com: not relevant (real-estate agency site).

— LIVE BROWSE SOURCES (no MCP needed) —
* 21st.dev: component patterns (sidebars, KPI cards, kanban, charts, empty
  states). Extract the pattern, REBUILD in vanilla CSS --js-* tokens.
* refero.design / styles.refero.design: real product screens + DESIGN.md library.
  Adapt patterns into our tokens; never clone a brand's identity.

— EXCLUDED ON PURPOSE —
* Higgsfield: paid AI image/video generator; contradicts the no-decorative-AI
  direction; its MCP OAuth is broken anyway. Do not use in the app.

— WHAT WE'VE ALREADY BUILT (previews/, extend these) —
* dashboard-os.html (Career OS dashboard), analysis-report.html, applications.html,
  marketing.html. All share the --js-* token system.

================= STEP 4 — IDENTITY (Direction C, verbatim) =================
bg #F7F5F0 · surface #FCFBF8 · elevated #FFFFFF · inset #EFEDE6 · text #111214 ·
text-soft #45484F · text-muted #8A8D93 · border #E5E2DB · primary(cobalt) #2457E6
(actions/active/selected ONLY, ~5% of pixels) · success #22A66F (healthy/positive
only) · warning #C88A16. Categorical data-viz palette (data only, always with a
text label): saved #6E7681 · applied #2A9D8F · interview #C88A16 · offer #22A66F.
Dark mode RE-MAPPED behind a Light/Dark/System toggle. Type: Instrument Serif
(one editorial moment/view), Inter (UI/body), JetBrains Mono (labels/numbers).

================= STEP 5 — HARD RULES =================
One self-contained HTML file, vanilla CSS + inline SVG line icons. No React/
Tailwind/shadcn, no emoji icons, no AI media. Light/Dark/System, responsive to
360px, visible keyboard focus, prefers-reduced-motion, motion mostly still. Real
JobSpike copy, no lorem, honest sample-data labels. AVOID: purple, gradients,
glassmorphism, 3D, neon/glowing borders, rainbow charts, color as the ONLY
carrier of meaning, and the two jobspike.in tells (CHAPTER-numbering, "quiet").

DELIVER as an artifact, then STOP for approval.
```
