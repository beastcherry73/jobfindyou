"""Adzuna job-search API wrapper.

Thin, dependency-light client for Adzuna's public jobs search endpoint.
Docs: https://developer.adzuna.com/  — free tier: 1,000 calls/month.

Credentials come from env only, by NAME: ADZUNA_APP_ID / ADZUNA_APP_KEY.
Never hardcode or log the key.

The search endpoint shape (country "in" for India):
  GET https://api.adzuna.com/v1/api/jobs/in/search/{page}
      ?app_id=...&app_key=...&results_per_page=...&what=...&where=...
Response: {"count": int, "results": [ {title, company:{display_name},
  location:{display_name}, salary_min, salary_max, created, description,
  redirect_url, id}, ... ]}
"""

import os
import logging
import time
import requests as http_requests

logger = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"

# Adzuna's four employment-type filter flags. Each is an independent boolean the
# API ANDs into the query; we expose them as one "job type" choice in the UI.
JOB_TYPE_PARAMS = {"full_time", "part_time", "contract", "permanent"}
# Adzuna's documented sort_by values.
SORT_BY_VALUES = {"default", "hybrid", "date", "salary", "relevance"}


class AdzunaError(Exception):
    """Raised when the Adzuna search cannot be completed (config/network/API)."""


class AdzunaValidationError(Exception):
    """Raised for bad *user* filter input (e.g. salary_min > salary_max).

    Distinct from AdzunaError so the route can answer 400 (your filters are
    invalid) instead of 502 (the upstream service failed)."""


def adzuna_configured():
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def _pos_int(value):
    """Return int(value) if it parses to a value >= 0, else None."""
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n >= 0 else None


def search_jobs(what="", where="", page=1, country="in", results_per_page=15,
                distance=None, salary_min=None, salary_max=None,
                salary_include_unknown=None, job_type=None, category=None,
                sort_by=None, max_days_old=None):
    """Query Adzuna and return normalized listings.

    Returns {"count": int, "results": [normalized_listing, ...]}.
    Raises AdzunaValidationError on conflicting/invalid filter input (so the
    route can answer 400), and AdzunaError on missing config or any
    request/parse failure (so the route can surface an honest error instead of
    a fabricated result set).

    Salary bounds are interpreted by Adzuna in the local currency of the
    `country` index — for the "in" index that is INR — so no currency picker
    is needed here.
    """
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaError(
            "Job search is not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY."
        )

    try:
        page = max(1, int(page))
    except (ValueError, TypeError):
        page = 1
    try:
        rpp = max(1, min(50, int(results_per_page)))
    except (ValueError, TypeError):
        rpp = 15

    # ── Validate salary bounds up front (conflicting filters must not silently
    # return an empty set) ────────────────────────────────────────────────
    smin = _pos_int(salary_min)
    smax = _pos_int(salary_max)
    if smin is not None and smax is not None and smin > smax:
        raise AdzunaValidationError(
            "Minimum salary can't be higher than maximum salary."
        )

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": rpp,
        "content-type": "application/json",
    }
    if what:
        params["what"] = what
    if where:
        params["where"] = where
    dist = _pos_int(distance)
    if dist:
        params["distance"] = dist
    if smin is not None:
        params["salary_min"] = smin
    if smax is not None:
        params["salary_max"] = smax
    if salary_include_unknown:
        params["salary_include_unknown"] = 1
    if job_type in JOB_TYPE_PARAMS:
        params[job_type] = 1
    if category:
        params["category"] = str(category).strip()
    if sort_by in SORT_BY_VALUES:
        params["sort_by"] = sort_by
    mdo = _pos_int(max_days_old)
    if mdo:
        params["max_days_old"] = mdo

    url = f"{ADZUNA_BASE}/{country}/search/{page}"
    try:
        resp = http_requests.get(url, params=params, timeout=15)
    except http_requests.RequestException as e:
        logger.warning(f"Adzuna request failed: {e}")
        raise AdzunaError("Could not reach the job search service. Please try again.")

    if resp.status_code == 400:
        # Adzuna rejects a malformed filter (e.g. an unknown category tag).
        logger.warning(f"Adzuna 400: {resp.text[:200]}")
        raise AdzunaValidationError(
            "One of the filters was rejected by Adzuna. Adjust and try again."
        )
    if resp.status_code == 401 or resp.status_code == 403:
        logger.error(f"Adzuna auth rejected: {resp.status_code}")
        raise AdzunaError("Job search credentials were rejected by Adzuna.")
    if resp.status_code == 429:
        logger.warning("Adzuna rate limit hit (429).")
        raise AdzunaError("Job search rate limit reached. Please try again later.")
    if resp.status_code != 200:
        logger.warning(f"Adzuna non-200: {resp.status_code} {resp.text[:200]}")
        raise AdzunaError("Job search returned an error. Please try again.")

    try:
        data = resp.json()
    except ValueError:
        raise AdzunaError("Job search returned an unreadable response.")

    results = []
    for r in data.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        company = ""
        if isinstance(r.get("company"), dict):
            company = (r["company"].get("display_name") or "").strip()
        location = ""
        if isinstance(r.get("location"), dict):
            location = (r["location"].get("display_name") or "").strip()
        results.append({
            "id": str(r.get("id", "")),
            "title": (r.get("title") or "").strip(),
            "company": company,
            "location": location,
            "salary_min": r.get("salary_min"),
            "salary_max": r.get("salary_max"),
            "salary_is_predicted": str(r.get("salary_is_predicted", "0")) == "1",
            "created": r.get("created", ""),
            "description": (r.get("description") or "").strip(),
            "redirect_url": r.get("redirect_url", ""),
        })

    count = data.get("count", len(results))
    try:
        count = int(count)
    except (ValueError, TypeError):
        count = len(results)

    return {"count": count, "results": results}


# ── Categories (real options from Adzuna, never a hardcoded guess) ─────────
# Adzuna's category list per country is stable, so cache it in-process for a
# day to avoid spending the limited free-tier call budget on every page load.
_CATEGORIES_CACHE = {}          # country -> {"ts": epoch, "items": [...]}
_CATEGORIES_TTL = 24 * 60 * 60


def list_categories(country="in"):
    """Return Adzuna's job categories for a country as [{tag, label}, ...].

    GET https://api.adzuna.com/v1/api/jobs/{country}/categories
    Response: {"results": [{"tag": "it-jobs", "label": "IT Jobs"}, ...]}
    Raises AdzunaError on missing config or request failure.
    """
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaError(
            "Job search is not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY."
        )

    cached = _CATEGORIES_CACHE.get(country)
    if cached and (time.time() - cached["ts"]) < _CATEGORIES_TTL:
        return cached["items"]

    url = f"{ADZUNA_BASE}/{country}/categories"
    params = {"app_id": app_id, "app_key": app_key, "content-type": "application/json"}
    try:
        resp = http_requests.get(url, params=params, timeout=15)
    except http_requests.RequestException as e:
        logger.warning(f"Adzuna categories request failed: {e}")
        raise AdzunaError("Could not load job categories. Please try again.")

    if resp.status_code != 200:
        logger.warning(f"Adzuna categories non-200: {resp.status_code} {resp.text[:200]}")
        raise AdzunaError("Could not load job categories. Please try again.")

    try:
        data = resp.json()
    except ValueError:
        raise AdzunaError("Job categories returned an unreadable response.")

    items = []
    for c in data.get("results", []) or []:
        if not isinstance(c, dict):
            continue
        tag = (c.get("tag") or "").strip()
        label = (c.get("label") or "").strip()
        if tag and label:
            items.append({"tag": tag, "label": label})

    _CATEGORIES_CACHE[country] = {"ts": time.time(), "items": items}
    return items
