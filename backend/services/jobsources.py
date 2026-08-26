"""Multi-source job search dispatcher.

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
import requests as http_requests

from backend.services.adzuna_service import (
    search_jobs as adzuna_search,
    ADZUNA_COUNTRIES,
    AdzunaError,
    AdzunaValidationError,
)

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
            "adzuna": code in ADZUNA_COUNTRIES,
            "currency": CURRENCY_SYMBOLS.get(code, ""),
        }
        for code, name, _ in _COUNTRY_ROWS
    ]


def any_source_configured():
    return bool(
        (os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))
        or os.environ.get("CAREERJET_API_KEY")
        or os.environ.get("JOOBLE_API_KEY")
        or os.environ.get("RAPIDAPI_KEY")
    )


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
def _careerjet(what, where, locale, page):
    key = os.environ.get("CAREERJET_API_KEY")
    if not key:
        return None
    params = {
        "affid": key,
        "keywords": what or "",
        "location": where or "",
        "locale_code": locale,
        "page": max(1, page),
        "pagesize": 20,
        "sort": "relevance",
        "user_ip": "0.0.0.0",
        "user_agent": "JobSpike/1.0",
    }
    try:
        r = http_requests.get(
            "http://public.api.careerjet.net/search",
            params=params,
            headers={"Referer": "https://www.jobspike.in/app/jobs",
                     "User-Agent": "JobSpike/1.0"},
            timeout=15,
        )
    except http_requests.RequestException as e:
        logger.warning(f"Careerjet request failed: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"Careerjet non-200: {r.status_code} {r.text[:120]}")
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    if d.get("type") != "JOBS":
        return {"count": 0, "results": []}
    # Careerjet's `url` is a jobviewtrack.com redirect that lands on
    # careerjet.co.uk (verified), and its `site` field comes back empty — so no
    # real publisher and not a direct apply link.
    out = [
        _norm("Careerjet", title=j.get("title"), company=j.get("company"),
              location=j.get("locations"), url=j.get("url"),
              desc=j.get("description"), created=j.get("date"),
              salary_text=j.get("salary"),
              publisher=(j.get("site") or "").strip() or "Careerjet",
              apply_is_direct=False)
        for j in (d.get("jobs") or [])
    ]
    try:
        count = int(d.get("hits", len(out)))
    except (ValueError, TypeError):
        count = len(out)
    return {"count": count, "results": out}


def _jooble(what, where, country_name, page):
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        return None
    loc = where or ""
    # Jooble infers country from the location string, so anchor it with the
    # country name (avoids "London" matching London, Kentucky).
    if country_name and country_name.lower() not in loc.lower():
        loc = (loc + ", " + country_name).strip(", ")
    try:
        r = http_requests.post(
            f"https://jooble.org/api/{key}",
            json={"keywords": what or "", "location": loc, "page": str(max(1, page))},
            timeout=15,
        )
    except http_requests.RequestException as e:
        logger.warning(f"Jooble request failed: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"Jooble non-200: {r.status_code} {r.text[:120]}")
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    # Jooble's `link` goes to its own jooble.org listing (verified), but its
    # `source` field DOES name the true original board (e.g. smartrecruiters.com)
    # — surface that as the publisher while being clear it isn't a direct link.
    out = [
        _norm("Jooble", title=j.get("title"), company=j.get("company"),
              location=j.get("location"), url=j.get("link"),
              desc=j.get("snippet"), created=j.get("updated"),
              salary_text=j.get("salary"),
              publisher=(j.get("source") or "").strip() or "Jooble",
              employment_type=j.get("type"),
              apply_is_direct=False)
        for j in (d.get("jobs") or [])
    ]
    try:
        count = int(d.get("totalCount", len(out)))
    except (ValueError, TypeError):
        count = len(out)
    return {"count": count, "results": out}


def _jsearch(what, where, country_code, page):
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        return None
    q = (what or "jobs").strip()
    if where:
        q = f"{q} in {where}"
    try:
        r = http_requests.get(
            "https://jsearch.p.rapidapi.com/search",
            params={"query": q, "page": str(max(1, page)), "num_pages": "1",
                    "country": country_code},
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
            timeout=20,
        )
    except http_requests.RequestException as e:
        logger.warning(f"JSearch request failed: {e}")
        return None
    if r.status_code != 200:
        # 403 here usually means the RapidAPI key isn't subscribed to JSearch yet.
        logger.warning(f"JSearch non-200: {r.status_code} {r.text[:120]}")
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    out = []
    for j in (d.get("data") or []):
        loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state"),
                                    j.get("job_country")] if x)
        # Prefer an apply_options entry flagged as the direct employer route;
        # fall back to job_apply_link. This is the one source that exposes the
        # ORIGINAL posting URL (LinkedIn/Glassdoor/company site) rather than its
        # own page.
        apply_url = j.get("job_apply_link") or ""
        publisher = j.get("job_publisher") or ""
        opts = j.get("apply_options")
        if isinstance(opts, list) and opts:
            direct = next((o for o in opts
                           if isinstance(o, dict) and o.get("is_direct")), None)
            chosen = direct or (opts[0] if isinstance(opts[0], dict) else None)
            if chosen:
                apply_url = chosen.get("apply_link") or apply_url
                publisher = chosen.get("publisher") or publisher
        out.append(_norm(
            "JSearch", title=j.get("job_title"), company=j.get("employer_name"),
            location=loc, url=apply_url, desc=j.get("job_description"),
            created=j.get("job_posted_at_datetime_utc"),
            salary_min=j.get("job_min_salary"), salary_max=j.get("job_max_salary"),
            publisher=publisher or "JSearch",
            employment_type=j.get("job_employment_type"),
            apply_is_direct=True))
    return {"count": len(out), "results": out}


def _fantastic(what, where, page):
    """Fantastic Jobs 'Active Jobs DB' (RapidAPI) — ATS/career-site listings only.

    Cleanest provenance of the sources we use: postings come straight from
    200k+ company career sites across 54 ATS platforms (Workday, Greenhouse,
    Lever, ...), so `url` is the employer's own ATS page — a genuinely direct
    apply link, not an aggregator redirect.

    Uses the same RAPIDAPI_KEY as JSearch (one RapidAPI key covers every API you
    subscribe to). Returns None when unsubscribed (403) so the caller falls
    through without cost or error.

    NOTE: response field names are handled defensively — this source could not
    be verified live because the key is not yet subscribed to it.
    """
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        return None
    host = "active-jobs-db.p.rapidapi.com"
    params = {"limit": 20, "offset": max(0, (max(1, page) - 1) * 20)}
    if what:
        params["title_filter"] = what
    if where:
        params["location_filter"] = where
    try:
        r = http_requests.get(
            f"https://{host}/active-ats-7d", params=params,
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}, timeout=20,
        )
    except http_requests.RequestException as e:
        logger.warning(f"Fantastic Jobs request failed: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"Fantastic Jobs non-200: {r.status_code} {r.text[:120]}")
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    rows = data if isinstance(data, list) else (data.get("data") or data.get("jobs") or [])
    out = []
    for j in rows:
        if not isinstance(j, dict):
            continue
        loc = j.get("locations_derived") or j.get("location") or j.get("locations")
        if isinstance(loc, list):
            loc = ", ".join(str(x) for x in loc if x)
        org = j.get("organization") or j.get("company") or j.get("employer")
        out.append(_norm(
            "Fantastic Jobs",
            title=j.get("title"), company=org, location=loc,
            url=j.get("url") or j.get("job_url") or j.get("apply_url"),
            desc=j.get("description") or j.get("description_text"),
            created=j.get("date_posted") or j.get("posted_at"),
            salary_text=j.get("salary_raw") or j.get("salary"),
            publisher=j.get("source") or j.get("ats") or "Employer ATS",
            employment_type=j.get("employment_type"),
            apply_is_direct=True))
    return {"count": len(out), "results": out}


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
    whose apply_url actually reaches the original posting (JSearch, Fantastic
    Jobs) are ranked above aggregator listings that only reach the aggregator's
    own page (Adzuna/Careerjet/Jooble) — the ranking the user approved. On a
    duplicate, the direct-apply copy wins so the better link survives.
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


def unified_search(what="", where="", country="in", page=1, **adzuna_filters):
    """Return {count, results, country, currency, source_used, sources_used}.

    Queries the direct-apply sources (JSearch, Fantastic Jobs) alongside the best
    aggregator for the country, then merges + de-duplicates and ranks real apply
    links first. Sources that are unconfigured or unsubscribed simply return
    nothing and are skipped at no cost.

    Adzuna serves its 18 countries with full filters and structured salary;
    Careerjet/Jooble provide the wider country coverage Adzuna lacks.
    AdzunaValidationError / AdzunaError propagate so the route answers 400/502
    honestly rather than silently returning an empty list.
    """
    country = (country or "in").strip().lower()
    info = _COUNTRY_INFO.get(country)
    name = info["name"] if info else country.upper()
    locale = info["cj"] if info else "en_" + country.upper()

    direct, aggregated = [], []
    total = 0

    def run(fn):
        try:
            return fn()
        except Exception as e:
            logger.warning(f"Job source error: {e}")
            return None

    # 1) Direct-apply sources — these carry the real publisher + original URL.
    for fn in (lambda: _jsearch(what, where, country, page),
               lambda: _fantastic(what, where, page)):
        r = run(fn)
        if r and r.get("results"):
            direct.extend(r["results"])

    # 2) Aggregator for country coverage / structured filters.
    if country in ADZUNA_COUNTRIES:
        try:
            res = adzuna_search(what=what, where=where, country=country,
                                page=page, **adzuna_filters)
        except AdzunaValidationError:
            raise  # bad user input (e.g. salary_min>max) -> route answers 400
        except AdzunaError as e:
            # Adzuna unconfigured/unreachable: don't fail the whole search when
            # other sources can still serve this country.
            logger.warning(f"Adzuna unavailable, falling back: {e}")
            res = None
        if res and res.get("results"):
            for j in res["results"]:
                j.setdefault("publisher", "Adzuna")
                j["apply_is_direct"] = False     # verified: lands on adzuna.*
                j.setdefault("apply_url", j.get("redirect_url", ""))
                j.setdefault("posted_at", j.get("created", ""))
            aggregated = res["results"]
            total = res.get("count", 0)

    if not aggregated:
        for fn in (lambda: _careerjet(what, where, locale, page),
                   lambda: _jooble(what, where, name, page)):
            r = run(fn)
            if r and r.get("results"):
                aggregated = r["results"]
                total = r.get("count", 0)
                break

    merged = _merge_rank_dedupe([direct, aggregated])
    if not merged:
        return {"count": 0, "results": [], "country": country, "currency": "",
                "source_used": "", "sources_used": []}

    # Report the upstream total where we have one (aggregators report a real
    # corpus count); otherwise fall back to what we actually merged.
    count = max(total, len(merged)) if total else len(merged)
    used = []
    for j in merged:
        if j.get("source") and j["source"] not in used:
            used.append(j["source"])

    return {
        "count": count,
        "results": merged,
        "country": country,
        "currency": ADZUNA_COUNTRIES.get(country, ""),
        "source_used": merged[0].get("source", ""),
        "sources_used": used,
    }
