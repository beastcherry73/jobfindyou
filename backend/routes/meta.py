import os
from flask import Blueprint, jsonify
from backend.database import db_diagnostic

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/api/health/db")
def db_health():
    """Safe database diagnostic endpoint.

    Reports only:
    - database backend (PostgreSQL / SQLite)
    - whether the required DB env var exists (boolean, NOT the value)
    - database host / project identifier derived from the URL (no credentials)
    """
    return jsonify(db_diagnostic())


@meta_bp.route("/api/health")
def health():
    """Health + a safe check of which job-search sources are configured.

    Reports presence booleans ONLY — never the key values — so you can confirm
    from the browser whether the running (e.g. Vercel) environment actually has
    each key set, without exposing any secret."""
    return jsonify({
        "status": "ok",
        "job_sources_configured": {
            "adzuna": bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY")),
            "careerjet": bool(os.environ.get("CAREERJET_API_KEY")),
            "jooble": bool(os.environ.get("JOOBLE_API_KEY")),
            "jsearch_rapidapi": bool(os.environ.get("RAPIDAPI_KEY")),
        },
        # Same presence-only contract, for the AI provider pool. Without this
        # there is no way to tell from outside whether the multi-provider
        # failover is actually ARMED in a given environment: the routing code
        # ships in the bundle, but a provider with no key is skipped silently,
        # so an environment holding only GROQ_API_KEY behaves exactly like the
        # old Groq-only chain and fails the same way when Groq is saturated.
        "ai_providers_configured": {
            "groq": bool(os.environ.get("GROQ_API_KEY")),
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "nvidia": bool(os.environ.get("NVIDIA_API_KEY")),
        },
    })