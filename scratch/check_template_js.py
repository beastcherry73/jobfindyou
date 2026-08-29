"""Parse every inline <script> in the templates and fail on a syntax error.

WHY THIS EXISTS
---------------
A logo fallback was written as an inline onerror="" handler, which needed
quotes nested three deep: a JS string, containing an HTML attribute,
containing more markup. One level lost its escaping and produced

    'onerror="...<span class='jp-letter'>' + initial + '...'
                          ^ closes the JS string here

which is a hard SyntaxError. Because it sits inside a template rather than a
.js file, nothing in the toolchain parsed it: the Python suites passed, the
Flask render returned HTTP 200 with the broken text happily embedded, and the
page shipped. The whole <script> block failed to parse in the browser, taking
the entire Job Search UI down, and it was a user who found it.

Rendering a template is NOT a check that its JavaScript is valid. This is.

HOW IT WORKS
------------
Extracts each inline <script> body, neutralises Jinja expressions (they are
not JavaScript), and runs `node --check` over the result. Requires node on
PATH; skips with a clear message if it is missing rather than passing quietly.

Run:  python scratch/check_template_js.py
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# <script> with a src= is an external file, not inline code.
_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)

# Jinja is not JavaScript. Replace each construct with a syntactically inert
# JS literal so the surrounding real code still parses.
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)     # {{ value }}
_JINJA_STMT = re.compile(r"\{%.*?%\}", re.S)       # {% if %}
_JINJA_CMNT = re.compile(r"\{#.*?#\}", re.S)       # {# note #}


def neutralise_jinja(js):
    js = _JINJA_CMNT.sub("", js)
    js = _JINJA_STMT.sub("", js)
    # A {{ }} usually stands where a value goes; 0 is valid in every such slot.
    js = _JINJA_EXPR.sub("0", js)
    return js


def check(path, node):
    src = open(path, encoding="utf-8", errors="replace").read()
    blocks = _SCRIPT_RE.findall(src)
    problems = []
    for i, body in enumerate(blocks):
        if not body.strip():
            continue
        js = neutralise_jinja(body)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(js)
            tmp = fh.name
        try:
            r = subprocess.run([node, "--check", tmp], capture_output=True,
                               text=True, timeout=60)
            if r.returncode != 0:
                # Map the reported line back to the template.
                offset = src[: src.index(body)].count("\n") + 1
                msg = (r.stderr or r.stdout).strip().splitlines()
                detail = next((l for l in msg if "SyntaxError" in l or "Error" in l), msg[-1] if msg else "?")
                lineno = ""
                m = re.search(r":(\d+)$", msg[0]) if msg else None
                if m:
                    lineno = f" (template line ~{offset + int(m.group(1)) - 1})"
                problems.append(f"script block #{i + 1}{lineno}: {detail}")
        finally:
            os.unlink(tmp)
    return len(blocks), problems


def main():
    node = shutil.which("node")
    if not node:
        print("node is not on PATH -- cannot parse template JavaScript.")
        print("This check is SKIPPED, not passed. Install Node to run it.")
        return 2

    files = sorted(
        glob.glob(os.path.join(_ROOT, "templates", "*.html"))
        + glob.glob(os.path.join(_ROOT, "templates", "partials", "*.html"))
    )
    total_blocks = 0
    failed = 0
    for f in files:
        n, problems = check(f, node)
        total_blocks += n
        rel = os.path.relpath(f, _ROOT).replace("\\", "/")
        if problems:
            failed += 1
            print(f"  FAIL  {rel}")
            for p in problems:
                print(f"          {p}")
        else:
            print(f"  ok    {rel}  ({n} inline script block{'s' if n != 1 else ''})")

    print()
    print(f"{len(files)} templates, {total_blocks} inline script blocks, {failed} file(s) with errors")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
