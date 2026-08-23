# JobSpike — Career OS Dashboard ENHANCEMENT prompt (for Opus 4.8)

Paste the block below into a fresh Opus 4.8 session. It enhances the existing
Career OS dashboard preview; it does not start from scratch.

---

```
ROLE: You are the design lead for JobSpike, an AI Career Operating System
(jobspike.in). You are ENHANCING an existing high-fidelity dashboard preview to
$10,000-agency quality. The visual identity is fixed (Direction C) — you are
refining IA, data-viz, hierarchy, and adding a disciplined touch of color. Do
NOT restyle the whole thing or migrate frameworks.

TASK: Improve previews/dashboard-os.html (the "Career OS" dashboard). It already
has: a Resume→Skills→Job Match→Applications→Interviews→Career "OS spine", Resume
Health ring + diagnostic bars, Your Next Move, Job Match (bullet bar + strengths/
gaps chips), an application funnel, the "Career Signal" composite index, and a
career-progress timeline. It is good but reads slightly plain and flat.

========================= STEP 0 — READ (binding) =========================
- All of design-references/ (00–06) + inspirations/, especially refero-*.
- CLAUDE.md (product + stack: Flask + server-rendered templates + vanilla JS +
  custom CSS + Chart.js; NEVER React/Tailwind/shadcn).
- The current file: previews/dashboard-os.html (build on it, don't discard it).

===================== STEP 1 — INVOKE SKILLS + COMMANDS =====================
Invoke these skills (via the Skill tool): frontend-design, artifact-design,
dataviz. Then run this ui-ux-pro-max command stack (Windows Python path shown;
use python / python3 / py -3 as available) and synthesize the results:

python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "career resume SaaS professional dashboard calm premium" --design-system -f markdown
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "dashboard information hierarchy one focal point" --domain ux
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "muted categorical palette data visualization accessible" --domain color
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "application funnel pipeline progress" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "north star composite index score vs target bullet" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "skill gap match coverage proportion keyword" --domain chart
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "empty state first run onboarding" --domain ux
python "C:\Users\venut\.claude\skills\ui-ux-pro-max\scripts\search.py" "semantic color tokens css variables" --stack html-tailwind

DO NOT use higgsfield-websites (wrong stack) or any AI-generated media. Higgsfield
is excluded from the app per 13-higgsfield-excluded.md.

===================== STEP 2 — DESIGN INTEL (don't re-derive) ==============
Direction C tokens (verbatim, from 01-jobspike-identity):
  bg #F7F5F0 · surface #FCFBF8 · elevated #FFFFFF · inset #EFEDE6 · text #111214
  · text-soft #45484F · text-muted #8A8D93 · border #E5E2DB
  · primary(cobalt) #2457E6 — actions/active nav/selected ONLY (~5% of pixels)
  · success #22A66F — healthy/improved ONLY · warning #C88A16 · error #C94A4A
  Dark mode is RE-MAPPED (bg #131417, elevated #22252B, cobalt #4E7BF0,
  green #35C286), behind a Light/Dark/System toggle.
Type: Instrument Serif (one editorial moment/view), Inter (UI/body),
  JetBrains Mono (labels/numbers/dates), tabular-nums on stacked figures.

Refero DESIGN.md discipline to hold (from styles.refero.design):
  Mercury — one accent for ONE action; separate surfaces by a one-step value
    lift, NOT drop shadows; headings at medium weight, never 700.
  Dub — 1px hairline borders (not shadows); ONE committed action color; radius
    vocabulary pill/12/8; soft-tint pill badges; product-UI imagery only.
  Relate — single blue for pipeline-active dots; green/amber/coral as SUPPORTING
    status only, never a second brand color.
  Origin — three-voice type (serif=emotion, sans=UI, mono=data).
  Linear — calm shell, ~5% accent, near-zero decoration.

Pro Max rules already verified:
  Funnel — label EVERY stage as text, highlight the biggest drop-off, never
    color-only. Bullet chart — labeled value + target marker, color supplementary.
  WCAG 2.2 — any drag has a pointer+keyboard alternative; async counts use
    role="status" aria-atomic, not a bare number.
  Style — Swiss/Minimalism; anti-patterns to avoid: "no live preview, weak ATS
    signals, decorative clutter."

===================== STEP 3 — WHAT TO FIX (the critique) ==================
1. Sharpen hierarchy: right now Resume Health, the OS spine, and Career Signal
   compete for "hero." Choose the OS spine + Career Signal as the identity pair;
   let Resume Health be clearly secondary (slightly smaller). One dominant focal.
2. The spine over-promises: Skills 79% and Interviews 2 have no destination.
   Keep them as pipeline nodes but make their state read as "tracked," and add a
   tiny "next" affordance so they don't look like dead ends.
3. Add a designed FIRST-RUN / empty variant note or a second artboard: what the
   dashboard looks like with no resume yet ("Upload a resume and your Career
   Signal begins"). An empty screen must be an invitation, never blank.
4. Career Signal needs a "How is this calculated?" affordance (popover/inline
   note) — a composite index reads as vanity unless it's explainable.
5. Add the mobile top-nav (the sidebar currently just disappears < 1000px).
6. Give the funnel and timeline a visually-hidden data-table fallback for a11y.
7. Add a one-line upload trust/privacy note somewhere honest.

===================== STEP 4 — THE COLOR DECISION ==========================
The dashboard is a touch plain. Fix it the disciplined way — add color that
ENCODES meaning, not decoration. Introduce a muted, warm-harmonized CATEGORICAL
palette used ONLY inside data-viz (the OS spine nodes, the funnel stages, and
optionally the Career Signal streams), never as UI chrome. Cobalt stays reserved
for actions; this categorical set is a SEPARATE system.

  --js-cat-saved     #6E7681  (dark #8A93A0)   — slate, "saved"
  --js-cat-applied   #2A9D8F  (dark #3BB6A6)   — teal, "in motion"
  --js-cat-interview #C88A16  (dark #E0A93B)   — ochre, "interview"
  --js-cat-offer     #22A66F  (dark #35C286)   — green, "offer/success"
This reads as a cool→warm→green progression toward success and gives the pipeline
real, legible color. Keep saturation low so it never fights the ivory. Also OK:
a single very-subtle tinted surface behind the Career Signal band to make the
signature metric feel special. HARD NO: purple, gradients, glassmorphism, 3D,
neon/glowing borders, rainbow charts, color as the ONLY carrier of meaning.

===================== STEP 5 — TYPOGRAPHY / HERO / LAYOUT ===================
Typography scale (apply consistently): mono eyebrows 10–12px tracked; Inter body
16/1.5 at ~65ch; Inter UI steps 12·13·14·16·18·20·24; Instrument Serif for the
greeting only (30–40px) on the app. Numbers tabular.
Hierarchy/layout: tighten to reduce the long scroll — group Resume Health + Next
Move tightly; make the OS spine + Career Signal the visual anchors; keep exactly
one cobalt primary action visible. Section rhythm generous but not sparse.
(Marketing hero is a separate task: serif "Your career. Engineered." + real
product UI as the hero visual + one ambient moment — do NOT build it here.)

===================== HARD RULES ==========================================
- One self-contained HTML file, vanilla CSS using --js-* tokens + inline SVG line
  icons. No React/Tailwind/shadcn, no emoji icons, no AI media.
- Light/Dark/System toggle (dark re-mapped), responsive to 360px, visible
  keyboard focus, prefers-reduced-motion respected, motion mostly still.
- Real JobSpike copy, no lorem; label sample data honestly.
- Keep everything the current preview already does well: ivory base, cobalt-for-
  actions, restrained green, editorial serif, thin borders, clean spacing, the
  Resume Health circular score + diagnostic bars.

DELIVER as an artifact I can open, then STOP for approval. Do NOT touch
workspace.html, index.html, backend/, or the database.
```
