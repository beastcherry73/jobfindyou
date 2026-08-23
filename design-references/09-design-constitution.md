# JobSpike Design Constitution

Every UI change must be checked against this file before being shipped.
If a change violates a "Never" rule, stop and flag it — don't ship it
anyway because it "looks fine."

## Never do this (the actual AI-slop patterns)

- Purple-to-blue gradient backgrounds, buttons, or text. Ever.
- backdrop-blur / glassmorphism on more than one element per screen.
- Emoji used as icons. Use Lucide or Phosphor icon components only.
- More than one border-radius value on a page. We use 12px. Nothing else.
- Decorative floating blob/orb shapes in a background.
- A glow/box-shadow halo around buttons or cards for "premium" feel.
- Center-aligned body paragraphs (only headlines may center-align).
- Every stat card using an identical icon-in-colored-circle pattern.
- Generic marketing words in UI copy: "Supercharge," "Unlock," "Elevate,"
  "Seamless," "Effortless," "Powered by AI" as a standalone badge.
- Stock isometric illustration style (people floating at laptops).
- More than 2 accent colors visible on one screen at once.
- A single font family used for both headlines and body when the
  reference design uses a deliberate pairing.
- Fake testimonials, fake avatars, fake star ratings, fake logos.
- Loading states that are just a bare spinner with no context text.
- Empty states that just say "No data yet" with nothing else.

## Always do this instead

- Every color must have a stated meaning before it's used (e.g. "blue =
  match relevance, green = health score, gold = brand accent — used on
  at most 2 elements per screen"). If a color has no stated meaning,
  don't add it.
- Every spacing value must come from this scale: 4, 8, 12, 16, 24, 32,
  48, 64px. No arbitrary values like 18px or 30px.
- Every new screen must reference an actual existing screenshot or URL
  as ground truth, not a text description. If none is given, ask for
  one before building.
- Real copy only. If real copy isn't available yet, write a single
  honest placeholder sentence, not lorem ipsum and not hype copy.
- Typographic hierarchy must vary — not every heading is the same size
  as every other heading. State the actual scale being used (e.g.
  48/32/20/16/14px) in the PR description.
- Empty states get one sentence of real guidance plus one clear action
  button, matching the tone of the rest of the product.
- Animation is limited to: number/ring count-up on load, single
  200ms fade-in on first paint, hover states. Nothing else moves
  unless explicitly requested.

## Process rule

Before writing any UI code, state in plain text:
1. Which reference (screenshot/URL) you're matching
2. The exact color values, font pairing, and spacing scale you're using
3. Which "Never" rules could plausibly be triggered by this task, and
   how you're avoiding them

If you can't answer #1 with something concrete, stop and ask instead
of defaulting to a generic pattern.

## JobSpike token values (2026-08-23)

| Token | Value |
|---|---|
| Background (light) | `#F7F5F0` warm ivory |
| Background (dark) | `#141310` warm near-black — not `#000`, not blue-black |
| Primary/interactive accent | Cobalt `#2457E6` (light) / `#5680F2` (dark) — the one color used for actions, links, active states |
| Brand accent | Gold `#B8942A`/`#D2AB4E` — one restrained premium touch, at most 2 elements per screen, never on primary actions |
| Success/health | `#1E9E5A` green — used only for real health/success signals, never decoration |
| Headline/name accent | Serif italic (JobSpike uses Instrument Serif, already the deployed choice) — used only for the user's name and the page's one hero line, never body copy or buttons |
| Body font | Inter — everywhere else |
| Data font | JetBrains Mono — scores, dates, tabular numbers |
| Card radius | 12px, everywhere, no exceptions (pills/avatars/checkboxes keep their own conventional shapes — this rule targets cards and panels) |
| Card shadow | One shadow value, reused everywhere — never a different shadow per component |
| Spacing scale | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64px — nothing outside this scale |
| Icons | SVG line icons only, consistent stroke width — no emoji |

Note: an earlier draft of this brief said "pick gold OR cobalt, not both" in
one place and "use both, with distinct meaning" in another. Resolved as: keep
both — cobalt is too deeply wired into the live app (buttons, active states,
the marketing site) to remove, and gold's value was always as a *restrained*
second accent, never a competitor to cobalt. The rule that survives from
both versions: no more than 2 accent colors visible on one screen, and gold
never carries a primary action.
