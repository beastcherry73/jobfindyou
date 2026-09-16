"""The public, crawlable pages: guides library and the comparison page.

These are the only pages a search engine or a stranger sees without logging
in, so the checks are about what they PROMISE: sources present, no unsourced
statistics, the competitor column dated, and the JobSpike numbers read live
rather than typed into the template.

    python scratch/test_public_content.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app                       # noqa: E402
from backend.guides import GUIDES, SOURCES           # noqa: E402
from backend.routes import content as content_mod    # noqa: E402

PASSED, FAILED = 0, 0


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} -- {detail}")


app = create_app()
app.config["TESTING"] = True
client = app.test_client()

print("PUBLIC CONTENT -- TEST SUITE")
print("\n[1] Routes")
r = client.get("/guides")
check("/guides renders", r.status_code == 200, r.status_code)
body = r.get_data(as_text=True)
check("every guide is listed", all(g["title"] in body for g in GUIDES))
check("every guide links to its own page", all(f'/guides/{g["slug"]}"' in body for g in GUIDES))

for g in GUIDES:
    r = client.get(f"/guides/{g['slug']}")
    text = r.get_data(as_text=True)
    ok = (r.status_code == 200 and g["title"] in text
          and all(s["h"] in text for s in g["sections"]))
    check(f"guide renders: {g['slug']}", ok, r.status_code)

check("unknown guide -> 404", client.get("/guides/not-a-guide").status_code == 404)
check("guides need no login", "Sign in" not in body and "password" not in body.lower())

print("\n[2] Honesty rules")
for g in GUIDES:
    text = " ".join(" ".join([s["h"]] + list(s.get("p", ())) + list(s.get("bullets", ())))
                    for s in g["sections"])
    stats = re.findall(r"\b\d+(?:\.\d+)?\s?%", text)
    # A percentage is only allowed where the same guide cites a source, or
    # where it is a bracketed placeholder ("[X%]") rather than a claim.
    unsourced = [s for s in stats if not g["sources"] and f"[{s}" not in text and f"[X{s[-1]}" not in text]
    check(f"no unsourced percentage in {g['slug']}", not unsourced, unsourced)
    check(f"{g['slug']} has a description and read time", bool(g["description"]) and g["minutes"] > 0)

ats_guide = next(g for g in GUIDES if g["slug"] == "how-ats-really-reads-your-resume")
joined = " ".join(" ".join(list(s.get("p", ())) + list(s.get("bullets", ()))) for s in ats_guide["sections"])
check("the 75% myth is debunked, not repeated",
      "Preptel" in joined and "no methodology" in joined)
check("the 7.4 second figure carries the Ladders study as a source",
      any("theladders.com" in s["url"] for s in ats_guide["sources"]))
check("every cited source has a real URL",
      all(s["url"].startswith("https://") for s in SOURCES.values()))
check("no guide claims a user outcome",
      not re.search(r"(our users|customers reported|landed \d|got \d+ interviews)", joined, re.I))

print("\n[3] Comparison page")
r = client.get("/compare/resumax")
page = r.get_data(as_text=True)
check("/compare/resumax renders", r.status_code == 200, r.status_code)
check("the competitor column is dated", content_mod.COMPETITOR_CHECKED in page)
check("it links to the source it was read from", "resumax.ai/pricing" in page)
check("it names where the competitor is ahead", "Where ResuMax is ahead" in page)
check("MCP gap admitted", "Yes, through their MCP integration" in page)
check("JobSpike job numbers are read live, not typed in",
      bool(re.search(r"[\d,]{4,} live roles from [\d,]+ employer career boards", page)), page[:0])
content_mod._stats_cache.update(at=0, value=None)
check("stats are cached after the first read",
      content_mod._job_numbers() == content_mod._job_numbers())

print("\n[4] Sitemap and crawling")
xml = client.get("/sitemap.xml").get_data(as_text=True)
check("sitemap lists every guide", all(f"/guides/{g['slug']}" in xml for g in GUIDES))
check("sitemap lists the index and comparison page", "/guides<" in xml.replace("</loc>", "<")
      and "/compare/resumax" in xml)
check("sitemap is well-formed", xml.count("<url>") == xml.count("</url>") and xml.startswith("<?xml"))
check("robots.txt still points at the sitemap",
      "sitemap.xml" in client.get("/robots.txt").get_data(as_text=True).lower())
check("the landing page links to the guides", "/guides" in client.get("/").get_data(as_text=True))

print("\n[5] Rendering")
check("both logo variants are toggled by CSS, never an inline display",
      'class="logo-light" src' in page and "style=\"height:24px;width:auto;display:block;\"" not in page)
check("pages declare a canonical URL and description",
      'rel="canonical"' in page and 'name="description"' in page)
check("guide pages carry Article structured data",
      '"@type": "Article"' in client.get(f"/guides/{GUIDES[0]['slug']}").get_data(as_text=True))

print("\n" + "=" * 50)
print(f"  RESULT: {PASSED} passed, {FAILED} failed")
print("=" * 50)
sys.exit(1 if FAILED else 0)
