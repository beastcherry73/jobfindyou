# JobSpike — Master Build Prompt (reusable)

Paste this as the FIRST message in a fresh, low-token session to build any
JobSpike screen at agency quality. Fill in the two blanks at the top.

---

## The prompt

```
You are the design lead for JobSpike (AI Career OS, jobspike.in). Build one
authenticated screen to $10,000-agency quality — not a rough sketch.

SCREEN: <dashboard | analysis report | improve | builder | applications | workspace>
DENSITY: <calm (dashboard/workspace) | working (analysis/builder)>

READ FIRST (binding context, do not skip):
- All of design-references/ (00-index, 01-identity, 02-doctrine,
  03-signature-patterns, 04-external-references) and the inspirations/ folder,
  especially the refero-* picks (Linear, Mercury, Origin, Relate, Dub).
- CLAUDE.md for product/stack facts.

USE THESE SKILLS (invoke them, don't wing it):
- frontend-design  -> aesthetic direction, avoiding templated defaults
- ui-ux-pro-max    -> palettes, layout patterns, UX guidelines, chart specs
- artifact-design  -> the delivery + theming discipline (MANDATORY before writing)
- dataviz          -> any chart/score/sparkline (ring, area, stat tiles)

IDENTITY (Direction C — non-negotiable, use --js-* tokens verbatim from 01):
- Warm ivory base #F7F5F0, surface #FCFBF8, elevated #FFFFFF, inset #EFEDE6.
- Cobalt #2457E6 for ONE primary action + active nav + selected states ONLY
  (~5% of pixels). Green #22A66F for healthy/improved/success ONLY.
- Instrument Serif (3-5 words, one hero/section moment), Inter (all UI/body),
  JetBrains Mono (labels, numbers, dates). Tabular-nums on stacked figures.
- Dark mode = re-mapped (see 01), shipped behind a Light/Dark/System toggle.

BORROW THESE PATTERNS AT HIGH FIDELITY — rebuilt in --js-* tokens, NEVER cloned
brand-for-brand (see per-pick specs in this folder / section below):
- Linear  -> app-shell restraint, accent held to ~5%, near-zero decoration.
- Mercury -> hero-metric framing; display weight ~medium not bold; separation by
             one-step elevation, not drop shadows; single accent for one action.
- Dub     -> light canvas + 1px hairline borders (not shadows); ONE committed
             action color; tidy list/row + understated area charts; pill badges
             with soft tints; a fixed radius vocabulary (pills / 12 cards / 8 btn).
- Origin  -> three-voice type (serif=emotion, sans=UI, mono=data); encouraging-
             but-honest coach copy; milestone/progress framing.
- Relate  -> single royal-blue for pipeline-active dots; semantic green/amber/
             coral as SUPPORTING status only; list+detail; the stage spine.

SIGNATURE PATTERNS (from 03 — use the ones the screen needs):
NOW/NEXT/MOVING narrative · score-as-instrument (ring + causal factors + trend
sparkline) · receipt-style before/after · composition-donut navigator · stage
spine · card-expand-to-detail · version diff · Improve = three choices · the
Light/Dark/System appearance selector.

HARD CONSTRAINTS:
- One self-contained HTML file. Vanilla CSS + inline SVG line icons only.
  NO React / Tailwind / shadcn. NO emoji as UI icons. NO AI-generated media
  (Higgsfield is excluded from the app per 13-higgsfield-excluded.md).
- Do NOT use the `higgsfield-websites` skill — it builds a React/TanStack/
  Cloudflare app, which violates JobSpike's Flask + vanilla-CSS stack. The app
  is always hand-authored HTML/CSS.
- Higgsfield media (if ever) is for the MARKETING page hero only, never an
  authenticated screen — and only once its OAuth is fixed (currently broken:
  RFC 9207 issuer mismatch, mcp.higgsfield.ai vs clerk.higgsfield.ai).
- Responsive to 360px, visible keyboard focus, prefers-reduced-motion respected,
  motion budget per 02 (mostly still; stagger once on load).
- Real JobSpike copy, no lorem. Label sample data honestly.
- Avoid every item on the doctrine's "AI-slop" hard-no list.

DELIVER as an artifact I can open, then STOP and show me. Do NOT touch
workspace.html, index.html, backend/, or the database until I approve.

If I add a line "Match this reference: <screenshot/link>", switch to exact-match
mode and replicate THAT specific screen's layout faithfully in --js-* tokens.
```

---

## Concrete Refero DESIGN.md specs (fetched from styles.refero.design)

Review the source pages (each has a DESIGN.md / CSS Variables / Design Tokens tab):
- Mercury  -> styles.refero.design/style/3172cd4d-118a-4a16-a259-6b634d32322e
- Origin   -> styles.refero.design/style/c60f05ff-2420-4a24-92db-80c4b6a74683
- Dub      -> styles.refero.design/style/b0d80806-b724-4ed1-a1d1-074edd3c9bc9
- Relate   -> styles.refero.design/style/337ade6a-4bae-49ba-b4aa-8994ac805a81
- Linear   -> search "Linear" on styles.refero.design

Use these as the "high fidelity" evidence — the exact moves to reproduce in our
own tokens. None of these palettes ship as-is; we translate the *discipline*.

**Mercury** (dark fintech). Cobalt `#5266eb` used *exclusively* for the single
primary action per page. Cards one value-step lighter than canvas (`#1e1e2a` on
`#171721`), 12px radius, 32px padding, **no drop shadows** — separation by value.
Display face at an *intermediate* weight (480), never 700. 72px section rhythm.
One chromatic note only; status colors do not join the accent.
-> JobSpike take: our whole restraint model. Prove hierarchy with elevation, not
   shadow or hue; keep cobalt to one action; keep headings medium-weight.

**Dub** (light SaaS — closest structural match). Canvas `#fff`, hairline borders
`#e5e5e5` (**1px, not shadows**) hold the system together. Electric Blue `#2563eb`
is a highlight; Deep Sapphire `#1e40af` is *exactly one* primary action per
surface. Soft-tint pills for badges. Radius vocabulary: 9999 tags / 12 cards /
8 buttons. Body 16px/1.5, drop to 14px for dense data, 11-12px mono labels.
Imagery = product UI mockups, never stock/decoration.
-> JobSpike take: our list rows, score/status pills, card+border treatment, and
   the analyses/progress charts map almost 1:1. Adopt the radius vocabulary.

**Origin** (dark finance, warm). Three-voice type is explicit: serif display for
emotion, sans for UI, mono for data — differentiate surfaces by color step, not
shadow; reserve chromatic color for feature cards only; mono uppercase labels at
10-12px with tracking.
-> JobSpike take: validates Instrument Serif + Inter + JetBrains Mono exactly.
   Coach/progress tone: serious, warm, honest; mono eyebrows for our layer labels.

**Relate** (cool-white SaaS). One vivid royal-blue `#145aff` for headline
highlight, links, logo, and **pipeline-active dots**. Semantic green(win)/
amber(pending)/coral(lost) are *supporting* accents only, never a second brand
color. Hairline `#e2e8f0`, snow canvas `#fcfcfc`.
-> JobSpike take: the Applications stage spine — active node = cobalt, stage
   status = restrained semantic color, everything else quiet.

**Linear** (from 04 / product knowledge). The benchmark for calm app-shell craft:
precise spacing, quiet neutral surfaces, one accent used sparingly, keyboard-first,
motion only where it aids understanding.
-> JobSpike take: the sidebar+content shell and the discipline of near-zero
   decoration across every screen.
```
