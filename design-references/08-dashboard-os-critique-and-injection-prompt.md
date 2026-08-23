# Dashboard-OS Critique + Injection Prompt

Source reviewed: `previews/dashboard-os.html` ("Career OS Dashboard, preview v3").
Reviewed by running it live in-browser (light/dark, desktop/mobile) and validating
its palette with the `dataviz` skill's automated checker plus `ui-ux-pro-max`
lookups. All findings below are backed by that run, not guesses.

The prompt at the bottom is meant to be handed to a fresh Claude Code session
(Opus 4.8) to do the actual injection into `templates/workspace.html` +
`static/css/workspace.css`.

---

## Findings (validated)

### 1. Data honesty — the decision that has to happen BEFORE any visual injection

`dashboard-os.html` presents several metrics as live, measured data that the
real backend does not currently compute: **Job Match %**, **Career Signal**
(the weekly weighted composite of Resume Health/Job Match/Skill Coverage/
Application Momentum), **Interview Readiness %**, and the 4-item "AI Coach —
Action Plan" checklist (always the same four generic tasks, not derived from
a specific resume). The file's own header comment admits this: `sample data`.
This matches a standing project rule (see `CLAUDE.md` / prior session memory):
do not fabricate metrics for features without a real backend.

This is a product decision, not a styling one. Two honest paths — pick one
per metric before wiring markup:

- **Build it for real**: e.g. Job Match % could be computed today from the
  existing `dimension_scores` + job-description keyword overlap already
  returned by `/api/analyze`; Career Signal could be a real weighted blend of
  values already in the DB. Worth doing for metrics that are cheap to make
  real.
- **Cut or gate it**: if a metric has no real computation path yet (Career
  Signal's specific weighting, Interview Readiness), either drop the card or
  ship it visibly labeled "Coming soon" / behind a flag — never as a bare
  number that looks measured.

Do not let the injection pass quietly ship fabricated numbers to real users.

### 2. Overflow with zero discoverability affordance (confirmed in-browser)

Two components hide overflow behind `overflow-x:auto; scrollbar-width:none`
with no visible cue that more content exists:

- `.os-spine` (the 7-item stat strip: Resume/Skills/Job Match/Applications/
  Interviews/Career Signal/…) — `dashboard-os.html:151`
- `.mobile-nav` (the collapsed sidebar-as-top-nav on narrow widths) —
  `dashboard-os.html:129`

At both a ~1150px desktop width and 375px mobile width, the last 1–2 items
get hard-cut at the container edge with nothing — no fade, arrow, or dot —
telling the user there's more to scroll to. Fix: add an edge fade mask
(`mask-image: linear-gradient(...)`) plus a chevron affordance, or replace
horizontal scroll with a wrapping grid at the breakpoints where it matters.

### 3. Mobile nav pattern

Under ~600px the sidebar collapses into a cramped horizontal icon+label strip
(6 items) rather than a dedicated mobile pattern. Item hit areas measure well
under the 44×44px minimum touch target. Recommend either a bottom nav bar
(≤5 items, per `ui-ux-pro-max` guidance) or a hamburger + slide-out drawer —
not a shrunk copy of the desktop sidebar.

### 4. Palette contrast/lightness (validated via `dataviz`'s `validate_palette.js`)

Light mode — text-context failures:
- `#C88A16` (warn) on the ivory surface → **2.88:1**, fails the 3:1 floor.
- `#C9A84C` (gold accent) on the ivory surface → **2.23:1**, fails.
  Both are currently used for small text (e.g. the "Developing" readiness
  label, gold accent copy). Either darken these two hexes for text use, or
  restrict them to icons/large fills and never small text.

Dark mode — categorical lightness band failure:
- `#35C286` (good), `#E0A93B` (warn), `#E2B93B` (gold) all sit at L 0.73–0.80,
  bunched at the top of the passing band instead of spread across it, and
  the warn↔good pair sits right at the ΔE 8.0 floor for protanopia — legal
  only with secondary encoding. Respace the three across the band, and make
  sure status is never color-only (pair with an icon or text label, which
  most of this file already does via badges — keep that discipline
  everywhere the injection touches).

### 5. Information density

Before any user action, the dashboard stacks: 7-card stat strip → hero card →
2 more stat cards (Confidence, Readiness) → Job Match card → Application
pipeline → Career Signal composite → 4-item action checklist. That's 8
distinct data blocks in a flat vertical stack. Your own
`previews/workspace-redesign.html` already solved this with a 3-tier
Status → Action → Why structure — reuse that skeleton and slot the
dashboard-os components into it, rather than keeping a flat stack of 8 cards.

### 6. Brand distinctiveness — light mode good, dark mode generic

The light-mode "Welcome back, *Sri Charith*" heading (italic Instrument
Serif on ivory) is a genuine, restrained signature — protect it. Dark mode,
though, reverts to a fairly generic "near-black surface + single bright
accent" dashboard look, which is one of the three current AI-generated-design
defaults per `frontend-design` guidance. Since the actual JobSpike identity is
built on warm ivory + heritage gold (see `design-references/01-jobspike-identity.md`),
dark mode should still telegraph that — e.g. a warmer near-black instead of
neutral slate, and more deliberate (but still restrained, per project rule)
use of the gold accent — rather than defaulting to generic dark-SaaS.

### 7. Token duplication

`dashboard-os.html` defines its own local token block (`--js-bg`, `--js-primary`,
`--js-surface`, `--js-border`, …) whose hex values are already an exact match
for the real `--ws-*` tokens in `static/css/workspace.css` (confirmed:
`--js-primary:#2457E6` = `--ws-primary`, etc.). When injecting, map every
`--js-*` reference to the existing `--ws-*` token — do not paste in a second,
competing token system.

---

## The injection prompt (hand this to the next session)

```
You're working on JobSpike, a production Flask app. Read CLAUDE.md first —
it has hard rules (never touch main, never deploy, never fabricate metrics
without a backend, preserve every switchSection/data-section/onclick hook).

Goal: bring the "Career OS" dashboard direction from
previews/dashboard-os.html into templates/workspace.html + static/css/workspace.css,
on the current branch (redesign/direction-c-integration), fixing the issues
below as you go rather than porting them as-is. This is a structural pass on
the real, working template — not a from-scratch rebuild. Preserve every
existing element ID and function that loadDashboard() (and other JS) already
relies on; extend/restyle around them.

Before writing markup, resolve the data-honesty question per metric:
- Job Match %, Career Signal, Interview Readiness, and the 4-item "AI Coach"
  checklist in dashboard-os.html are sample data with no real backend today.
- For each: either wire it to a real computation (Job Match % and a
  diagnostics panel can be built today from the dimension_scores already
  returned by /api/analyze — see how templates/workspace.html's report view
  reads `data.dimension_scores` at its "Dimension scores" section for the
  exact field-access pattern), or cut the card, or ship it clearly labeled
  as a preview/coming-soon state. Do not ship a bare fabricated number.
- Metrics that ARE already real in the current template — healthScore/
  healthRing/healthStatus/healthChange, dashboardTopRec/aiNextActionText
  (from ai_recommendations.top_5_fixes), the timeline/trajectory dots, the
  Recent Analyses table, and interviewRate/callbackRate/offerRate/scoreTrend
  (real, from tracker data) — keep and restyle, don't discard.

Structural fixes to apply during the port (all validated against the preview,
not stylistic opinion):
1. Reduce the flat 8-card stack to a 3-tier Status → Action → Why layout —
   previews/workspace-redesign.html already has this skeleton; use it as the
   scaffold and slot the richer dashboard-os components (Job Match, pipeline,
   Career Signal if you decide to make it real) into the appropriate tier
   instead of stacking everything.
2. Any horizontally-scrolling strip (the stat strip, the mobile top-nav) needs
   a visible affordance — edge fade + chevron — or should switch to a
   wrapping grid at the breakpoint where items would otherwise get cut off
   with no indication there's more. Do not ship `overflow-x:auto` with
   `scrollbar-width:none` and nothing else.
3. Mobile nav: replace the shrunk horizontal icon+label strip with either a
   bottom nav (max 5 items, JobSpike's real sidebar has ~16 destinations so
   pick the top 5 + a "More" sheet) or a hamburger + drawer. Every tap target
   must be at least 44x44px.
4. Palette: in light mode, don't use #C88A16 or #C9A84C as text color (both
   fail 3:1 contrast on the ivory surface) — darken them for text contexts,
   keep the lighter values for icons/fills only. In dark mode, respace the
   good/warn/gold trio so they aren't all clustered at L 0.73-0.80, and never
   let status be color-only — every status already has a badge/label pattern
   in this file, keep that discipline in every new component you add.
5. Map every --js-* custom property from dashboard-os.html to the existing
   --ws-* token of the same value in static/css/workspace.css — do not
   introduce a second token system.
6. Dark mode should still read as JobSpike (warm near-black + the heritage
   gold accent used deliberately, per design-references/01-jobspike-identity.md),
   not a generic near-black-plus-single-accent dashboard.

When done: run the app locally (venv/Scripts/python.exe app.py), log in, and
verify the dashboard in both themes and at mobile width before calling this
finished. Do not push to main or deploy.
```
