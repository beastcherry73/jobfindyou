# 03_UI_RULES: Strict Interface & Styling Standards

All layout modifications must conform strictly to these design guidelines.

## Rule 1: Whitespace & Breathing Room
- Never crowd components together.
- Vertical space between landing sections: `140px` minimum.
- Padding inside cards: minimum `24px` on mobile, `36px` on desktop.
- List spacing: minimum `12px` gaps using CSS Flex/Grid.

## Rule 2: Color Integrity (No Hype Gradients)
- Avoid glowing purple/pink neon bubbles. Use the **Arctic Horizon** system.
- Light text color: `#F8F5EF` (Cream) or `#FFFFFF` (White).
- Dark text color: `#08111F` (Dark Navy) or `#475569` (Slate Gray).
- Never use solid black `#000` for backdrops; use `#08111F` or `#0F172A`.

## Rule 3: Cards, Borders & Shadow Limits
- Maximum border radius: `24px` for wrappers, `20px` for standard cards, `8px` to `12px` for small indicators.
- Shadow opacity must remain below **25%** to prevent muddy visual weight.
- Borders must be thin, translucent lines (`1px solid rgba(8, 17, 31, 0.08)` for light, `1px solid rgba(124, 200, 255, 0.15)` for dark).

## Rule 4: Micro-interactions & Motion
- All CTA buttons must animate on hover (scale, translation, or box-shadow glow).
- Transition speeds: `0.2s` or `0.25s` using `ease` or `cubic-bezier(0.16, 1, 0.3, 1)` curves.
- Cursor coordinate tracking should be lightweight and performant.
