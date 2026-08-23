# JobSpike Design References

Persistent design context so any Claude Code session (or Opus 4.8) can pick up
exactly where we left off — no need to re-explain. Load ALL of these before
designing any JobSpike screen.

| File | What it holds |
|------|---------------|
| `01-jobspike-identity.md` | The brand north star + color/type tokens (Direction C). The non-negotiables. |
| `02-design-doctrine.md` | How we design: hierarchy, motion budget, restraint, anti-"AI-slop" rules. |
| `03-signature-patterns.md` | The distinctive components we invented for JobSpike. |
| `04-external-references.md` | Every outside inspiration, each with a keep/reject verdict + live browse sources (21st.dev, refero.design). |
| `09-design-constitution.md` | **Check this before shipping any UI change.** The Never/Always rules and exact token values (color, type, radius, shadow, spacing scale). |

## The one-line rule
Every design decision serves: **clarity > consistency > usability > hierarchy > polish > decoration.** If an element only looks impressive in a screenshot but doesn't help the user understand something faster, cut it.

## Stack constraint (hard)
JobSpike is **Flask + server-rendered templates + vanilla JS + custom CSS + Chart.js**. All design ships as **vanilla CSS using the `--js-*` tokens**. NEVER migrate to React, Tailwind, or shadcn. References that use those frameworks are for *ideas only* — extract the pattern, rebuild it in vanilla CSS.

## Preview-first workflow
Build a polished preview (a standalone HTML artifact) first. Do NOT edit
`workspace.html`, `index.html`, `backend/`, or the database until the human approves.
