"""Public, crawlable content: the guides library and the comparison page.

These are the only pages on the site with no login and no AI call, which is
what makes them worth having: they can be indexed, linked and shared. The
content itself lives in backend/guides.py.

The comparison page reads JobSpike's own job numbers live (cached briefly) so
it cannot quietly go stale, and states the date its competitor column was read.
"""
import json
import logging
import time

from flask import Blueprint, abort, render_template

from backend.guides import GUIDES, GUIDES_BY_SLUG, SITE
from backend.services import ats

content_bp = Blueprint("content", __name__)
logger = logging.getLogger(__name__)

# Read from resumax.ai's own pricing and home pages on this date. Anything in
# that column of the table must be re-checked, and this date changed, together.
COMPETITOR_CHECKED = "15 September 2026"

_STATS_TTL = 600
_stats_cache = {"at": 0.0, "value": None}


def _job_numbers():
    """(live listings, employer boards) for the comparison table.

    Cached for ten minutes: this is a public page, and every miss takes the
    shared database connection's lock. Falls back to the registry size and an
    empty count rather than failing the page.
    """
    now = time.time()
    if _stats_cache["value"] and now - _stats_cache["at"] < _STATS_TTL:
        return _stats_cache["value"]
    try:
        stats = ats.corpus_stats()
        value = (f"{stats['jobs']:,}", f"{stats['companies']:,}")
    except Exception as e:                       # never break a static page
        logger.warning(f"Comparison page stats unavailable: {e}")
        value = ("", f"{len(ats.load_registry()):,}")
    _stats_cache.update(at=now, value=value)
    return value


@content_bp.route("/guides")
def guides_index():
    return render_template(
        "public/guides_index.html", guides=GUIDES,
        page_title="Guides",
        page_description="Practical guides to resumes, applications and interviews, with every figure sourced.",
        canonical=f"{SITE}/guides",
        end_cta="Put one of these into practice.")


@content_bp.route("/guides/<slug>")
def guide(slug):
    item = GUIDES_BY_SLUG.get(slug)
    if not item:
        abort(404)
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": item["title"],
        "description": item["description"],
        "dateModified": item["updated"],
        "mainEntityOfPage": f"{SITE}/guides/{slug}",
        "publisher": {"@type": "Organization", "name": "JobSpike"},
    })
    return render_template(
        "public/guide.html", guide=item, schema=schema,
        page_title=item["title"], page_description=item["description"],
        canonical=f"{SITE}/guides/{slug}",
        end_cta="Check your resume against a real job description.")


@content_bp.route("/compare/resumax")
def compare_resumax():
    jobs_total, boards = _job_numbers()
    return render_template(
        "public/compare.html",
        jobs_total=jobs_total or "Tens of thousands of", boards=boards,
        competitor_checked=COMPETITOR_CHECKED,
        page_title="JobSpike vs ResuMax",
        page_description="A side-by-side of JobSpike and ResuMax on price, job board, tailoring, interview practice and salary data — including where ResuMax is ahead.",
        canonical=f"{SITE}/compare/resumax",
        end_cta="Try the free side for yourself.")
