"""Generate JobSpike's brand assets from the supplied wordmark.

INPUT
-----
`jobspike_logo.svg` (the full lockup: spike glyph + "JobSpike" wordmark).

A companion `jobspike_icon.svg` was described but never landed on disk, so the
square icon here is DERIVED from the lockup's own spike glyph -- same
coordinates, same #4F46E5, just isolated and centred. If a real icon file turns
up later, drop it in and re-run; nothing else needs to change.

OUTPUT
------
    static/img/jobspike-logo.svg        the lockup, verbatim as supplied
    static/img/jobspike-icon.svg        spike glyph alone, square
    static/img/jobspike-wordmark.svg    "JobSpike" text alone
    static/favicon.ico                  16 / 32 / 48 px
    static/img/favicon-32.png
    static/img/apple-touch-icon.png     180 px

WHY THE WORDMARK IS SPLIT OUT
The sidebar collapses to 56px, where only a 24px mark is visible. Showing the
whole lockup there would render the spike twice (once as the mark, once inside
the lockup), so the mark uses the icon and the expanded name uses the wordmark.

WHY PIL DRAWS THE ICON RATHER THAN RASTERISING THE SVG
No SVG rasteriser is installed (cairosvg/wand/svglib all absent) and adding one
is a dependency JobSpike does not need. The glyph is a 7-point polyline plus a
dot, so it is redrawn here at the same coordinates and supersampled 4x for
clean edges -- pixel output that matches the vector rather than approximating
it.

Run:  python scratch/build_brand_assets.py
"""

import io
import os
import shutil
import sys

from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"C:\Users\venut\OneDrive\Desktop\jobspike_logo.svg"
IMG_DIR = os.path.join(_ROOT, "static", "img")

BRAND = "#4F46E5"
INK = "#1E1B2E"

# Glyph geometry, lifted verbatim from the supplied SVG.
POINTS = [(0, 120), (35, 120), (55, 40), (75, 90), (95, 10), (115, 70), (140, 70)]
DOT = (95, 10, 9)          # cx, cy, r
STROKE = 10

# With the stroke's half-width the glyph occupies x -5..145, y 1..125.
# Centre that inside a 160x160 box.
BOX = 160
OFF_X, OFF_Y = 10, 17

ICON_SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}"
     width="{BOX}" height="{BOX}" role="img" aria-label="JobSpike">
  <g transform="translate({OFF_X}, {OFF_Y})">
    <polyline points="{' '.join(f'{x},{y}' for x, y in POINTS)}"
              fill="none" stroke="{BRAND}" stroke-width="{STROKE}"
              stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="{DOT[0]}" cy="{DOT[1]}" r="{DOT[2]}" fill="{BRAND}"/>
  </g>
</svg>
'''

WORDMARK_SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 90"
     width="400" height="90" role="img" aria-label="JobSpike">
  <text x="0" y="68" font-family="Arial, Helvetica, sans-serif"
        font-size="64" font-weight="700" fill="{INK}">Job<tspan fill="{BRAND}">Spike</tspan></text>
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


def main():
    if not os.path.isfile(SRC):
        print(f"Source logo not found: {SRC}")
        return 2
    os.makedirs(IMG_DIR, exist_ok=True)

    # 1. the lockup, exactly as supplied
    shutil.copyfile(SRC, os.path.join(IMG_DIR, "jobspike-logo.svg"))
    print("  static/img/jobspike-logo.svg      (copied verbatim)")

    # 2/3. derived pieces
    io.open(os.path.join(IMG_DIR, "jobspike-icon.svg"), "w", encoding="utf-8").write(ICON_SVG)
    print("  static/img/jobspike-icon.svg      (derived: spike glyph, centred)")
    io.open(os.path.join(IMG_DIR, "jobspike-wordmark.svg"), "w", encoding="utf-8").write(WORDMARK_SVG)
    print("  static/img/jobspike-wordmark.svg  (derived: text only)")

    # 4. raster
    ico_sizes = [16, 32, 48]
    frames = [draw_icon(n) for n in ico_sizes]
    ico_path = os.path.join(_ROOT, "static", "favicon.ico")
    frames[-1].save(ico_path, format="ICO",
                    sizes=[(n, n) for n in ico_sizes])
    print(f"  static/favicon.ico                ({'/'.join(map(str, ico_sizes))} px)")

    p32 = os.path.join(IMG_DIR, "favicon-32.png")
    draw_icon(32).save(p32, format="PNG")
    print("  static/img/favicon-32.png")

    # Apple wants an opaque tile; transparency renders black on iOS.
    apple = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    apple.alpha_composite(draw_icon(180))
    apple.convert("RGB").save(os.path.join(IMG_DIR, "apple-touch-icon.png"), format="PNG")
    print("  static/img/apple-touch-icon.png   (180 px, opaque)")

    print("\nsizes on disk:")
    for rel in ["static/favicon.ico", "static/img/favicon-32.png",
                "static/img/apple-touch-icon.png", "static/img/jobspike-logo.svg",
                "static/img/jobspike-icon.svg", "static/img/jobspike-wordmark.svg"]:
        f = os.path.join(_ROOT, rel)
        print(f"  {rel:36} {os.path.getsize(f):>7,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
