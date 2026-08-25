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
import requests as http_requests

logger = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"


class AdzunaError(Exception):
    """Raised when the Adzuna search cannot be completed."""


def adzuna_configured():
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def search_jobs(what="", where="", page=1, country="in", results_per_page=15,
                salary_min=None, full_time=None, sort_by=None):
    """Query Adzuna and return normalized listings.

    Returns {"count": int, "results": [normalized_listing, ...]}.
    Raises AdzunaError on missing config or any request/parse failure so the
    route can surface an honest error instead of a fabricated result set.
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
    if salary_min:
        try:
            params["salary_min"] = int(salary_min)
        except (ValueError, TypeError):
            pass
    if full_time:
        params["full_time"] = 1
    if sort_by in ("date", "salary", "relevance"):
        params["sort_by"] = sort_by

    url = f"{ADZUNA_BASE}/{country}/search/{page}"
    try:
        resp = http_requests.get(url, params=params, timeout=15)
    except http_requests.RequestException as e:
        logger.warning(f"Adzuna request failed: {e}")
        raise AdzunaError("Could not reach the job search service. Please try again.")

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
