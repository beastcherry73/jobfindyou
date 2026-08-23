# JobSpike Design Doctrine — how we design

## Hierarchy first
- One primary focal element per screen. Everything else is demonstrably quieter
  (smaller type, lower contrast, more whitespace). No walls of equal cards.
- Dashboard passes the **5-second test**: the user instantly sees resume health,
  the single best next action, recent work, and progress.
- Density is chosen per screen: dashboard = generous/calm; analysis report &
  builder = denser/working. Don't use one density everywhere.
- Content max-width ~1100–1200px. Body copy ≈65 characters wide.

## Motion budget (strict)
- Micro-interactions (hover, toggle): 150–250ms, ease-out.
- Panel/page transitions: 200–300ms, never block navigation on animation.
- Constant-rate motion (spinners/progress): linear easing.
- Entrances stagger ONCE on load — never re-run on every scroll.
- State must never depend on an animation finishing.
- Respect `prefers-reduced-motion`.
- Premium products are mostly still. Stillness reads as confident; constant
  motion reads as AI-generated.

## Colour restraint
- The accent (cobalt) appears in ~5% of pixels — the one thing that matters.
- Semantic status colour (success/warning/error) is a SEPARATE system from the
  accent. Green-means-good is not "the brand is green."
- Elevation (surface → elevated → inset) carries more hierarchy than adding hues.

## Components
- One card treatment everywhere. For emphasis change weight (border/tint), not
  the whole visual language.
- Exactly three button tiers: primary (ideally one per screen), secondary, ghost.
- Empty, loading, and error states are DESIGNED. An empty screen is an invitation
  to act ("Upload a resume and your score fills in"), never a bare "No data."
- Progressive disclosure: lead with the verdict/summary; detail lives behind
  tabs or accordions.

## Marketing vs. authenticated app
- Marketing page: more flourish allowed (one ambient moment is fine).
- Authenticated app: prioritize clarity. Motion/3D only where it improves
  comprehension. At most ONE earned 3D moment, and only if it carries meaning.

## Avoid the "AI-generated SaaS" look (hard no's)
Purple/violet AI gradients · neon or glowing borders · excessive glassmorphism ·
giant gradient typography · decorative 3D blobs/spheres · everything rounded ·
pill-shaped everything · heavy shadows everywhere · floating decorative objects ·
random/constant animation · emoji used as UI icons (use SVG line icons) ·
warm-cream+serif+terracotta cliché · near-black+acid-green cliché.

## Honesty
Mark every element **live** (backed by real JobSpike data/APIs) vs
**future / not implemented** (concept only). Never imply an API or capability
that doesn't exist. Mock data is fine for previews if clearly labelled.

## The two-question test for any borrowed idea
1. Does it help the user understand something faster, or just look impressive in a
   screenshot? Only the first justifies adoption.
2. Would Stripe / Linear ship this on their actual product dashboard (not their
   marketing site)? If it's a marketing-page move, it doesn't belong in the app.
