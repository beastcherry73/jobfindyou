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


def get_countries():
    """List for the UI dropdown: [{code, name, adzuna}] in display order."""
    return [
        {"code": code, "name": name, "adzuna": code in ADZUNA_COUNTRIES}
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
          created=None, salary_min=None, salary_max=None, salary_text=None):
    """Map any provider's record onto the listing shape the UI already renders."""
    return {
        "id": "",
        "title": _clean(title),
        "company": _clean(company),
        "location": _clean(location),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_is_predicted": False,
        "salary_text": _clean(salary_text) if salary_text else "",
        "created": created or "",
        "description": _clean(desc)[:400],
        "redirect_url": url or "",
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
    out = [
        _norm("Careerjet", title=j.get("title"), company=j.get("company"),
              location=j.get("locations"), url=j.get("url"),
              desc=j.get("description"), created=j.get("date"),
              salary_text=j.get("salary"))
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
    out = [
        _norm("Jooble", title=j.get("title"), company=j.get("company"),
              location=j.get("location"), url=j.get("link"),
              desc=j.get("snippet"), created=j.get("updated"),
              salary_text=j.get("salary"))
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
        out.append(_norm(
            "JSearch", title=j.get("job_title"), company=j.get("employer_name"),
            location=loc, url=j.get("job_apply_link"), desc=j.get("job_description"),
            created=j.get("job_posted_at_datetime_utc"),
            salary_min=j.get("job_min_salary"), salary_max=j.get("job_max_salary")))
    return {"count": len(out), "results": out}


def unified_search(what="", where="", country="in", page=1, **adzuna_filters):
    """Return {count, results, country, currency, source_used} for any country.

    Adzuna-covered countries use Adzuna (full filters + structured salary).
    Everywhere else — and when Adzuna comes back empty — we fall back through the
    global aggregators. AdzunaValidationError / AdzunaError from the Adzuna path
    propagate so the route can answer 400/502 honestly.
    """
    country = (country or "in").strip().lower()

    if country in ADZUNA_COUNTRIES:
        res = adzuna_search(what=what, where=where, country=country,
                            page=page, **adzuna_filters)
        if res.get("results"):
            res["source_used"] = "Adzuna"
            return res
        # Adzuna returned nothing — widen with the global aggregators below.

    info = _COUNTRY_INFO.get(country)
    name = info["name"] if info else country.upper()
    locale = info["cj"] if info else "en_" + country.upper()

    for fn in (
        lambda: _careerjet(what, where, locale, page),
        lambda: _jooble(what, where, name, page),
        lambda: _jsearch(what, where, country, page),
    ):
        try:
            r = fn()
        except Exception as e:
            logger.warning(f"Job source error: {e}")
            r = None
        if r and r.get("results"):
            r["country"] = country
            r["currency"] = ADZUNA_COUNTRIES.get(country, "")
            r["source_used"] = r["results"][0].get("source", "")
            return r

    return {"count": 0, "results": [], "country": country, "currency": "",
            "source_used": ""}
