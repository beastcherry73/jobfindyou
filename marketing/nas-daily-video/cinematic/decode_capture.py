"""Decodes a base64 image data-URL that overflowed into a javascript_tool
result file (harness double-escapes the JSON when it spills to disk --
one extra json.loads() unwraps it), and writes it as a PNG.

Usage: python decode_capture.py <tool_result_txt_path> <out_png_path>
"""
import base64
import json
import re
import sys


def main(txt_path, out_png):
    with open(txt_path, encoding="utf-8") as f:
        raw = f.read()
    outer = json.loads(raw)
    text = outer[0]["text"]
    inner, end = json.JSONDecoder().raw_decode(text)
    m = re.match(r"data:image/(\w+);base64,(.*)$", inner)
    if not m:
        raise SystemExit(f"not a data URL: {inner[:60]!r}")
    png = base64.b64decode(m.group(2))
    with open(out_png, "wb") as f:
        f.write(png)
    print(f"wrote {len(png)} bytes to {out_png}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
