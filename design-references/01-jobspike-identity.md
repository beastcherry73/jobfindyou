# JobSpike Identity — the north star

**Source of truth:** the live marketing page at jobspike.in. The authenticated
product must feel like the same company designed both. Do not redesign the
marketing page; extend its language inward.

## Personality
Professional · premium · intelligent · calm · trustworthy · human · product-focused.
Technical without being intimidating. It should say "a serious career product that
happens to have sophisticated AI" — NOT "an AI website with cool effects."

Marketing headline in use: **"Your career. Engineered."**

## Chosen direction: C — Hybrid
Warm-white base, pure-white cards, subtle depth. Editorial enough to match
marketing (serif accents, ivory tones), crisp enough that dense screens read
clearly. Dark mode ships as a toggle, not the default.

## Color tokens (LIGHT)
Cobalt is used ONLY for actions / active nav / selected states. Green means ONLY
healthy / improved / ATS-ready / success. Never flood the UI with either.

| Token | Hex | Use |
|-------|-----|-----|
| `--js-bg` | `#F7F5F0` | page background (warm ivory) |
| `--js-surface` | `#FCFBF8` | cards, rails |
| `--js-elevated` | `#FFFFFF` | raised cards, popovers |
| `--js-inset` | `#EFEDE6` | wells, tracks, inputs |
| `--js-text` | `#111214` | primary text |
| `--js-text-soft` | `#45484F` | body / secondary |
| `--js-text-muted` | `#8A8D93` | labels, meta |
| `--js-border` | `#E5E2DB` | hairlines |
| `--js-primary` | `#2457E6` | cobalt — actions/active/selected ONLY |
| `--js-primary-hover` | `#1D46C7` | |
| `--js-success` | `#22A66F` | healthy/improved/ATS-ready ONLY |
| `--js-warning` | `#C88A16` | warnings |
| `--js-error` | `#C94A4A` | errors |
| `--js-info` | `#3B82F6` | informational (distinct from cobalt action) |

Score scale: 70–100 green · 50–69 amber · 0–49 red — always paired with the
number AND a word, never colour alone.

## Color tokens (DARK — re-mapped, NOT inverted)
`--js-bg #131417` · `--js-surface #1A1C21` · `--js-elevated #22252B` ·
`--js-text #ECEAE4` · `--js-border #2A2E35` · cobalt lifted to `#4E7BF0` ·
green `#35C286`. Never pure black. Tune contrast intentionally.

## Typography
- **Instrument Serif** — display face, used with restraint (≈3–5 words: hero,
  one section title per view). The JobSpike signature, not a gimmick.
- **Inter** — all UI and body.
- **JetBrains Mono** — labels, eyebrows, numbers, dates, data. The "engineered" feel.
Numbers that stack in columns get `font-variant-numeric: tabular-nums`.

## Shape & depth
Radius restrained: 6–16px by component type. Pills reserved for status/tags only,
not every clickable thing. Shadows soft and warm-biased (navy/brown tint), never
pure-black, never heavy.

## Navigation = goals, not AI jargon
Sidebar names outcomes: **Dashboard · Resume Analysis · Improve Resume ·
Resume Builder · Applications · Career Workspace**. NEVER expose "AI Rewrite,
ATS Optimization, Bullet Optimization, Grammar Optimization" — those run underneath.
