"""Multi-source job search dispatcher.

The KEYLESS ATS LAYER comes first. Those listings are synced from employers'
own public job boards (Greenhouse/Lever/Ashby/SmartRecruiters/Workable/
Recruitee/Breezy) into our own Postgres, so they need no API key, their
`apply_url` reaches the employer's real application page, and — because we own
the data — every filter applies exactly and in combination. See
backend/services/ats.py.

Adzuna covers 18 countries with rich structured data (salary, categories) and
powers the full filter set there. For every other country we fall back to
global aggregators — Careerjet (~90 countries), Jooble (~70), and JSearch
(Google for Jobs) — so a user in essentially any country can search. Every
returned listing is labelled with its true source; we never fabricate listings
or hide where they came from.

Routing is primary + fallback (one live source per search, not all at once) to
respect each provider's free-tier quota. Order per country:

    Adzuna (if it serves that country) -> Careerjet -> Jooble -> JSearch

The first configured source that returns results wins. Credentials come from
env only, by NAME (ADZUNA_APP_ID/KEY, CAREERJET_API_KEY, JOOBLE_API_KEY,
RAPIDAPI_KEY); never hardcode or log a key.
"""

import os
import re
import html
import logging

from backend.services import ats
# ATS-only since 2026-08-29. The Adzuna client is no longer called; only its
# validation error type is still referenced, so the route's 400 handling for
# salary_min>max keeps working unchanged.
from backend.services.adzuna_service import AdzunaValidationError

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(txt):
    """Strip HTML tags/entities the aggregators embed in titles/snippets."""
    if not txt:
        return ""
    return html.unescape(_TAG_RE.sub(" ", str(txt))).strip()


# ── Country registry ───────────────────────────────────────────────────────
# (iso2, display name, Careerjet locale). Adzuna coverage is derived from
# ADZUNA_COUNTRIES. This spans every region so a user almost anywhere is
# covered; Careerjet/Jooble/JSearch serve the ~30 here that Adzuna cannot.
_COUNTRY_ROWS = [
    ("in", "India", "en_IN"), ("us", "United States", "en_US"),
    ("gb", "United Kingdom", "en_GB"), ("bd", "Bangladesh", "en_BD"),
    ("pk", "Pakistan", "en_PK"), ("lk", "Sri Lanka", "en_LK"),
    ("ae", "United Arab Emirates", "en_AE"), ("sa", "Saudi Arabia", "en_SA"),
    ("qa", "Qatar", "en_QA"), ("ph", "Philippines", "en_PH"),
    ("id", "Indonesia", "en_ID"), ("my", "Malaysia", "en_MY"),
    ("sg", "Singapore", "en_SG"), ("jp", "Japan", "en_JP"),
    ("hk", "Hong Kong", "en_HK"), ("kr", "South Korea", "en_KR"),
    ("th", "Thailand", "en_TH"), ("vn", "Vietnam", "en_VN"),
    ("au", "Australia", "en_AU"), ("nz", "New Zealand", "en_NZ"),
    ("ca", "Canada", "en_CA"), ("de", "Germany", "de_DE"),
    ("fr", "France", "fr_FR"), ("nl", "Netherlands", "nl_NL"),
    ("it", "Italy", "it_IT"), ("es", "Spain", "es_ES"),
    ("at", "Austria", "de_AT"), ("ch", "Switzerland", "de_CH"),
    ("pl", "Poland", "pl_PL"), ("ie", "Ireland", "en_IE"),
    ("se", "Sweden", "en_SE"), ("no", "Norway", "en_NO"),
    ("dk", "Denmark", "en_DK"), ("fi", "Finland", "en_FI"),
    ("be", "Belgium", "fr_BE"), ("pt", "Portugal", "pt_PT"),
    ("tr", "Turkey", "en_TR"), ("za", "South Africa", "en_ZA"),
    ("ng", "Nigeria", "en_NG"), ("ke", "Kenya", "en_KE"),
    ("eg", "Egypt", "en_EG"), ("br", "Brazil", "pt_BR"),
    ("mx", "Mexico", "es_MX"), ("ar", "Argentina", "es_AR"),
    ("cl", "Chile", "es_CL"), ("co", "Colombia", "es_CO"),
]
_COUNTRY_INFO = {code: {"name": name, "cj": cj} for code, name, cj in _COUNTRY_ROWS}

# Local currency symbol per country, so the UI's salary labels follow the
# selected country instead of defaulting to INR. (Adzuna's 18 markets also carry
# a numeric-format locale on the front end; these symbols cover all countries.)
CURRENCY_SYMBOLS = {
    "in": "₹", "us": "$", "gb": "£", "bd": "৳", "pk": "₨", "lk": "Rs",
    "ae": "AED", "sa": "SAR", "qa": "QAR", "ph": "₱", "id": "Rp", "my": "RM",
    "sg": "S$", "jp": "¥", "hk": "HK$", "kr": "₩", "th": "฿", "vn": "₫",
    "au": "A$", "nz": "NZ$", "ca": "C$", "de": "€", "fr": "€", "nl": "€",
    "it": "€", "es": "€", "at": "€", "ch": "CHF", "pl": "zł", "ie": "€",
    "se": "kr", "no": "kr", "dk": "kr", "fi": "€", "be": "€", "pt": "€",
    "tr": "₺", "za": "R", "ng": "₦", "ke": "KSh", "eg": "E£", "br": "R$",
    "mx": "MX$", "ar": "AR$", "cl": "CL$", "co": "CO$",
}


def get_countries():
    """List for the UI dropdown: [{code, name, adzuna, currency}] in display order."""
    return [
        {
            "code": code,
            "name": name,
            # Retained for payload compatibility, now always True: with the
            # aggregators gone every country is served by the same corpus and
            # honours the same filters exactly.
            "adzuna": True,
            "currency": CURRENCY_SYMBOLS.get(code, ""),
        }
        for code, name, _ in _COUNTRY_ROWS
    ]


def any_source_configured():
    """True when ANY source can serve a search.

    The keyless ATS layer needs no credentials at all, so a deployment with no
    third-party keys still has a working job search — which is why the registry
    counts as a configured source here.
    """
    return bool(
        ats.load_registry()
        or (os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))
        or os.environ.get("CAREERJET_API_KEY")
        or os.environ.get("JOOBLE_API_KEY")
        or os.environ.get("RAPIDAPI_KEY")
    )


# Adzuna models employment as four independent flags; our own corpus stores one
# normalized employment_type. Map the UI's single choice onto it.
_JOB_TYPE_TO_EMPLOYMENT = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "contract": "Contract",
    "permanent": "Full-time",
}


def _page_int(page):
    """Coerce a page value to a positive int.

    request.args gives us STRINGS, and every aggregator client below did
    `max(1, page)` on the raw value — which raises TypeError comparing str to
    int and, because unified_search swallows source errors, silently dropped
    that source from the results whenever the UI sent a page parameter. Coerce
    once, here.
    """
    try:
        return max(1, int(page))
    except (TypeError, ValueError):
        return 1


def _norm(source, title=None, company=None, location=None, url=None, desc=None,
          created=None, salary_min=None, salary_max=None, salary_text=None,
          publisher=None, employment_type=None, apply_is_direct=False):
    """Map any provider's record onto ONE normalized schema.

    Schema: title, company, location, salary(min/max/text), employment_type,
    posted_at, publisher, apply_url, source.

    `apply_url` is whatever the provider gives us. `apply_is_direct` records
    whether that URL actually reaches the original posting (employer/ATS/board)
    or merely the aggregator's own page — verified empirically: Adzuna,
    Careerjet and Jooble all land on their own sites, so they are False. The UI
    uses this to label the CTA honestly ("View on Adzuna") instead of implying
    a direct application.

    `redirect_url`/`created` are kept as aliases so existing callers (results
    rendering, the Apply->tracker flow) keep working unchanged.
    """
    url = url or ""
    return {
        "id": "",
        "title": _clean(title),
        "company": _clean(company),
        "location": _clean(location),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_is_predicted": False,
        "salary_text": _clean(salary_text) if salary_text else "",
        "employment_type": _clean(employment_type),
        "posted_at": created or "",
        "created": created or "",          # alias (existing UI/date formatting)
        "publisher": _clean(publisher) or source,
        "apply_url": url,
        "redirect_url": url,               # alias (existing Apply/tracker flow)
        "apply_is_direct": bool(apply_is_direct),
        "description": _clean(desc)[:400],
        "source": source,
        "currency": "",
    }


# ── Global aggregator clients (each returns {count, results} or None) ───────
def _dedupe_key(job):
    """Identity for de-duplication: title + company + location, normalized.

    Aggregators frequently carry the same posting (JSearch in particular repeats
    a job across publishers), so collapse on the human identity of the role
    rather than on URL or provider id.
    """
    def squash(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    # Location wording varies a lot between sources for the same job
    # ("London" vs "London, UK" vs "London, England, UK"), so key on the primary
    # locality only — the first comma-separated segment. Keeping some location
    # avoids collapsing genuinely different postings of the same role in
    # different cities.
    loc = squash((job.get("location") or "").split(",")[0])
    return (squash(job.get("title")), squash(job.get("company")), loc)


def _merge_rank_dedupe(groups):
    """Flatten source result groups, drop duplicates, rank direct-apply first.

    `groups` is an ordered list of result lists. Within the merged set, listings
    whose apply_url actually reaches the original posting (the keyless ATS
    layer, JSearch, Fantastic Jobs) are ranked above aggregator listings that
    only reach the aggregator's own page (Adzuna/Careerjet/Jooble). The sort is
    stable, so within that direct-apply tier the group order is preserved and
    employer-board listings lead. On a duplicate, the direct-apply copy wins so
    the better link survives.
    """
    best = {}
    order = []
    for jobs in groups:
        for job in jobs or []:
            if not job.get("title"):
                continue
            k = _dedupe_key(job)
            prev = best.get(k)
            if prev is None:
                best[k] = job
                order.append(k)
            elif job.get("apply_is_direct") and not prev.get("apply_is_direct"):
                best[k] = job          # upgrade to the direct-apply duplicate
    merged = [best[k] for k in order]
    merged.sort(key=lambda j: 0 if j.get("apply_is_direct") else 1)
    return merged


def unified_search(what="", where="", country="in", page=1, per_page=20,
                   **adzuna_filters):
    """Return {count, results, country, currency, source_used, sources_used}.

    ATS-ONLY as of 2026-08-29. Every result now comes from our synced copy of
    employers' own public job boards, so every `apply_url` reaches the real
    employer application page.

    The five third-party sources were removed deliberately:

      Adzuna, Careerjet, Jooble  aggregators whose links land on their OWN
          site, not the employer's -- `apply_is_direct` was False for all
          three. Adzuna was additionally PREEMPTING the other two: they only
          ran inside `if not aggregated`, so wherever Adzuna answered (its 18
          markets, India included) Careerjet's and Jooble's results were
          fetched and silently discarded.
      JSearch     returned HTTP 403 not-subscribed on this plan; it had been
          contributing nothing for some time.
      Fantastic Jobs  same aggregator problem, no direct apply.

    Consequence, stated plainly: coverage is now exactly our registry's
    coverage. Countries where few employers use these seven platforms return
    far fewer results than before, and the fix is to grow the registry rather
    than to re-add an aggregator.

    AdzunaValidationError still propagates for salary_min>max so the route
    answers 400; the name is legacy and kept only to avoid churning the route.
    """
    country = (country or "in").strip().lower()

    # Corpus-only filters: not part of the historical Adzuna kwarg set, so they
    # are popped before the rest is forwarded.
    work_mode = (adzuna_filters.pop("work_mode", "") or "").strip().lower()
    experience_level = (adzuna_filters.pop("experience_level", "") or "").strip().lower()

    # Salary sanity check. Previously this was enforced inside the Adzuna
    # client; with Adzuna gone the API would silently return an empty list for
    # min>max, so it is enforced here. The exception type is unchanged because
    # the route already maps it to a 400.
    smin, smax = adzuna_filters.get("salary_min"), adzuna_filters.get("salary_max")
    try:
        if smin is not None and smax is not None and smin != "" and smax != "":
            if float(smin) > float(smax):
                raise AdzunaValidationError(
                    "Minimum salary cannot be higher than maximum salary.")
    except (TypeError, ValueError):
        pass    # unparseable numbers are ignored, as before

    res = ats.search(
        what=what, where=where, country=country, page=page, per_page=per_page,
        what_exclude=adzuna_filters.get("what_exclude") or "",
        work_mode=work_mode,
        experience_level=experience_level,
        employment_type=_JOB_TYPE_TO_EMPLOYMENT.get(adzuna_filters.get("job_type") or ""),
        salary_min=smin,
        salary_max=smax,
        salary_include_unknown=True,
        max_days_old=adzuna_filters.get("max_days_old"),
        sort_by=(adzuna_filters.get("sort_by") or "relevance"),
    )
    results = (res or {}).get("results") or []

    used = []
    for j in results:
        if j.get("source") and j["source"] not in used:
            used.append(j["source"])

    # `count` is now the number of rows that ACTUALLY match in our corpus, so
    # it is reachable by paging. The old value summed the aggregators' upstream
    # totals and reported figures like "263,758 results found" above 34 visible
    # cards with no way to reach the rest.
    return {
        "count": (res or {}).get("count", len(results)),
        "results": results,
        "country": country,
        "currency": CURRENCY_SYMBOLS.get(country, ""),
        "source_used": results[0].get("source", "") if results else "",
        "sources_used": used,
    }
