"""Generate JobSpike's brand assets.

OUTPUT
------
    static/img/jobspike-logo.svg            the lockup: spike + wordmark
    static/img/jobspike-logo-on-dark.svg    the same, for dark surfaces
    static/img/jobspike-icon.svg            spike glyph alone, square
    static/img/jobspike-wordmark.svg        "JobSpike" alone
    static/img/jobspike-wordmark-on-dark.svg
    static/favicon.ico                      16 / 32 / 48 px
    static/img/favicon-32.png
    static/img/apple-touch-icon.png         180 px

WHY THE WORDMARK IS OUTLINED RATHER THAN <text>
The wordmark used to be an SVG `<text>` element set in
`Arial, Helvetica, sans-serif`. That was wrong twice over. The site is set in
Inter, so the logo rendered in a different typeface from the nav link sitting
directly beside it; and `<text>` resolves against whatever fonts the VIEWER
has, so the wordmark changed shape on any machine without Arial. Glyph
outlines lifted from the vendored Inter Bold remove both problems: it is
genuinely the brand face, and it is identical everywhere because there is no
font to resolve.

WHY THERE ARE -on-dark VARIANTS
"Job" was hardcoded #1E1B2E. On the auth page's dark theme (--auth-card
#1B1A16) that is near-black on near-black, so the logo read as "Spike" with a
smudge in front of it. These files are loaded through `<img>`, which cannot see
the page's `color` or its `[data-theme]` attribute, so the colour cannot be
inherited - a second file, swapped by CSS, is the fix that works in every
browser. On dark the indigo is lightened too: #4F46E5 on #1B1A16 is 2.3:1,
which is too weak, and #8B85F5 is 5.6:1.

WHY THE WORDMARK IS SPLIT OUT FROM THE LOCKUP
The sidebar collapses to 56px, where only the 24px mark shows. Using the whole
lockup there would render the spike twice (once as the mark, once inside the
lockup), so the mark uses the icon and the expanded name uses the wordmark.

WHY PIL DRAWS THE RASTER ICON RATHER THAN RASTERISING THE SVG
No SVG rasteriser is installed (cairosvg/wand/svglib all absent) and adding one
is a dependency JobSpike does not need. The glyph is a 7-point polyline plus a
dot, so it is redrawn here at the same coordinates and supersampled 4x for
clean edges -- pixel output that matches the vector rather than approximating
it.

Requires fontTools (dev-time only; nothing at runtime imports it).

Run:  python scratch/build_brand_assets.py
"""

import glob
import io
import os
import sys

from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(_ROOT, "static", "img")
INTER_DIR = os.path.join(_ROOT, "static", "fonts.gstatic.com", "s", "inter", "v20")

BRAND = "#4F46E5"
INK = "#1E1B2E"
# Dark-surface palette. INK_DARK matches the auth page's --auth-text; the
# indigo is lifted because the brand indigo is only 2.3:1 on #1B1A16.
BRAND_DARK = "#8B85F5"
INK_DARK = "#ECEAE4"

WORD_A, WORD_B = "Job", "Spike"
FONT_SIZE = 64.0          # font units are scaled to this em size

# Spike geometry, lifted verbatim from the supplied logo.
POINTS = [(0, 120), (35, 120), (55, 40), (75, 90), (95, 10), (115, 70), (140, 70)]
DOT = (95, 10, 9)          # cx, cy, r
STROKE = 10

# With the stroke's half-width the glyph occupies x -5..145, y 1..125.
# Centre that inside a 160x160 box.
BOX = 160
OFF_X, OFF_Y = 10, 17


# ---------------------------------------------------------------- type ----

def _inter_bold():
    """The vendored Inter Bold face.

    Google serves Inter as hash-named files, so the weight cannot be read off
    the filename - each candidate is opened and identified by its name table.
    """
    from fontTools.ttLib import TTFont
    for path in sorted(glob.glob(os.path.join(INTER_DIR, "*.ttf"))):
        f = TTFont(path, lazy=True)
        family = (f["name"].getDebugName(1) or "").strip()
        sub = (f["name"].getDebugName(2) or "").strip()
        if family == "Inter" and sub == "Bold":
            return f, path
        f.close()
    raise SystemExit(f"Inter Bold not found under {INTER_DIR}")


def _outline(font, text, matrix):
    """SVG path data for `text`, with `matrix` applied to every glyph."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    a, b, c, d, e, f = matrix
    pen = SVGPathPen(glyphs)
    x = 0.0
    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            raise SystemExit(f"Inter has no glyph for {ch!r}")
        g = glyphs[name]
        # Offset this glyph by the pen position, in font units, before the
        # shared scale/flip is applied.
        g.draw(TransformPen(pen, (a, b, c, d, e + x * a, f + x * b)))
        x += g.width
    return pen.getCommands(), x


def _advance(font, text):
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    return sum(glyphs[cmap[ord(ch)]].width for ch in text)


def _run_bounds(font, text):
    """Tight ink bounds of the whole run, in font units."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.transformPen import TransformPen

    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    bp = BoundsPen(glyphs)
    x = 0.0
    for ch in text:
        g = glyphs[cmap[ord(ch)]]
        g.draw(TransformPen(bp, (1, 0, 0, 1, x, 0)))
        x += g.width
    return bp.bounds          # (xMin, yMin, xMax, yMax)


def build_wordmark(font, upem, ink, brand):
    """Two-tone outlined wordmark, tightly cropped to its own ink."""
    s = FONT_SIZE / upem
    x0, y0, x1, y1 = _run_bounds(font, WORD_A + WORD_B)
    pad = FONT_SIZE * 0.06

    # Place the baseline so the ink sits `pad` from the top of the viewBox.
    left = x0 * s - pad
    baseline = y1 * s + pad
    height = (y1 - y0) * s + pad * 2
    width = (x1 - x0) * s + pad * 2

    m = (s, 0, 0, -s, -left, baseline)
    d_a, adv_a = _outline(font, WORD_A, m)
    m_b = (s, 0, 0, -s, -left + _advance(font, WORD_A) * s, baseline)
    d_b, _ = _outline(font, WORD_B, m_b)

    return (f'''<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {width:.2f} {height:.2f}"
     width="{width:.2f}" height="{height:.2f}" role="img" aria-label="JobSpike">
  <path fill="{ink}" d="{d_a}"/>
  <path fill="{brand}" d="{d_b}"/>
</svg>
''', width, height)


# --------------------------------------------------------------- marks ----

def icon_svg(brand=BRAND):
    pts = " ".join(f"{x},{y}" for x, y in POINTS)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}"
     width="{BOX}" height="{BOX}" role="img" aria-label="JobSpike">
  <g transform="translate({OFF_X}, {OFF_Y})">
    <polyline points="{pts}"
              fill="none" stroke="{brand}" stroke-width="{STROKE}"
              stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="{DOT[0]}" cy="{DOT[1]}" r="{DOT[2]}" fill="{brand}"/>
  </g>
</svg>
'''


def lockup_svg(font, upem, ink, brand):
    """Spike + wordmark on one baseline-ish centre line."""
    s = FONT_SIZE / upem
    x0, y0, x1, y1 = _run_bounds(font, WORD_A + WORD_B)
    word_w = (x1 - x0) * s
    word_h = (y1 - y0) * s

    # The spike occupies x -5..145, y 1..125 once the stroke is accounted for.
    spike_w, spike_h = 150.0, 124.0
    scale = (word_h * 1.42) / spike_h          # mark a little taller than the x-height run
    sw, sh = spike_w * scale, spike_h * scale
    gap = word_h * 0.62

    pad = FONT_SIZE * 0.06
    height = max(sh, word_h) + pad * 2
    width = sw + gap + word_w + pad * 2

    spike_y = (height - sh) / 2.0
    word_baseline = (height + word_h) / 2.0
    word_x = pad + sw + gap

    m = (s, 0, 0, -s, word_x - x0 * s, word_baseline)
    d_a, _ = _outline(font, WORD_A, m)
    m_b = (s, 0, 0, -s, word_x - x0 * s + _advance(font, WORD_A) * s, word_baseline)
    d_b, _ = _outline(font, WORD_B, m_b)

    pts = " ".join(f"{x},{y}" for x, y in POINTS)
    return f'''<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {width:.2f} {height:.2f}"
     width="{width:.2f}" height="{height:.2f}" role="img" aria-label="JobSpike">
  <g transform="translate({pad + 5 * scale:.2f}, {spike_y - 1 * scale:.2f}) scale({scale:.5f})">
    <polyline points="{pts}"
              fill="none" stroke="{brand}" stroke-width="{STROKE}"
              stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="{DOT[0]}" cy="{DOT[1]}" r="{DOT[2]}" fill="{brand}"/>
  </g>
  <path fill="{ink}" d="{d_a}"/>
  <path fill="{brand}" d="{d_b}"/>
</svg>
'''


def draw_icon(size, scale=4):
    """Render the glyph at `size` px, supersampled for clean edges."""
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s / float(BOX)

    def pt(x, y):
        return ((x + OFF_X) * k, (y + OFF_Y) * k)

    width = max(1, int(round(STROKE * k)))
    xy = [pt(x, y) for x, y in POINTS]
    # joint="curve" gives the rounded joins the SVG asks for.
    d.line(xy, fill=BRAND, width=width, joint="curve")
    # Round the free ends, which `line` leaves square.
    r = width / 2.0
    for (cx, cy) in (xy[0], xy[-1]):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BRAND)
    # The accent dot at the peak.
    dcx, dcy = pt(DOT[0], DOT[1])
    dr = DOT[2] * k
    d.ellipse([dcx - dr, dcy - dr, dcx + dr, dcy + dr], fill=BRAND)

    return img.resize((size, size), Image.LANCZOS)


def write(rel, text):
    path = os.path.join(_ROOT, rel)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    print(f"  {rel:42} {os.path.getsize(path):>7,} bytes")


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    font, font_path = _inter_bold()
    upem = font["head"].unitsPerEm
    print(f"wordmark set in {os.path.basename(font_path)} (Inter Bold, upem={upem})\n")

    light, w, h = build_wordmark(font, upem, INK, BRAND)
    dark, _, _ = build_wordmark(font, upem, INK_DARK, BRAND_DARK)
    write("static/img/jobspike-wordmark.svg", light)
    write("static/img/jobspike-wordmark-on-dark.svg", dark)

    write("static/img/jobspike-logo.svg", lockup_svg(font, upem, INK, BRAND))
    write("static/img/jobspike-logo-on-dark.svg",
          lockup_svg(font, upem, INK_DARK, BRAND_DARK))

    write("static/img/jobspike-icon.svg", icon_svg())

    ico_sizes = [16, 32, 48]
    frames = [draw_icon(n) for n in ico_sizes]
    ico_path = os.path.join(_ROOT, "static", "favicon.ico")
    frames[-1].save(ico_path, format="ICO", sizes=[(n, n) for n in ico_sizes])
    print(f"  {'static/favicon.ico':42} {os.path.getsize(ico_path):>7,} bytes")

    p32 = os.path.join(IMG_DIR, "favicon-32.png")
    draw_icon(32).save(p32, format="PNG")
    print(f"  {'static/img/favicon-32.png':42} {os.path.getsize(p32):>7,} bytes")

    # Apple wants an opaque tile; transparency renders black on iOS.
    apple_path = os.path.join(IMG_DIR, "apple-touch-icon.png")
    apple = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    apple.alpha_composite(draw_icon(180))
    apple.convert("RGB").save(apple_path, format="PNG")
    print(f"  {'static/img/apple-touch-icon.png':42} {os.path.getsize(apple_path):>7,} bytes")

    print(f"\nwordmark viewBox: {w:.1f} x {h:.1f}  (aspect {w / h:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
