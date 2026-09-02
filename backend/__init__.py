import os
from urllib.parse import urlunsplit

from flask import Flask, redirect, request, jsonify
from .config import configure_app
from .routes import register_blueprints


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
        ),
        static_folder=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"
        ),
    )
    configure_app(app)
    register_blueprints(app)

    # ── Canonical host: jobspike.in -> www.jobspike.in ─────────────────
    #
    # Both hosts served identical 200s, so search engines saw two copies of
    # every page and analytics split visitors across two hostnames.
    #
    # The direction is NOT arbitrary. Google OAuth's redirect_uri is pinned to
    # https://www.jobspike.in/auth/google/callback (config.py) and Google
    # matches it EXACTLY, so www has to stay the canonical host; sending www to
    # the apex instead would have broken Google sign-in.
    #
    # Scope is deliberately narrow - only safe, idempotent page requests on the
    # bare apex:
    #   * /api/* is excluded. A 301 can drop the Authorization header, and the
    #     Vercel cron calls /api/jobs/ats/sync with a bearer token. Crawlers do
    #     not index the API, so canonicalizing it buys nothing and risks a lot.
    #   * only GET/HEAD. Redirecting a POST can turn it into a GET and silently
    #     discard an uploaded resume.
    #   * exact host match, so a preview *.vercel.app deployment and localhost
    #     are untouched and no redirect loop is possible.
    @app.before_request
    def canonical_host():
        host = (request.host or "").split(":")[0].lower()
        if host != "jobspike.in":
            return None
        if request.method not in ("GET", "HEAD"):
            return None
        if request.path.startswith("/api/"):
            return None
        return redirect(
            urlunsplit(("https", "www.jobspike.in", request.path,
                        request.query_string.decode("utf-8", "ignore"), "")),
            code=301,
        )

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": e.name, "details": e.description}), e.code
        return e

    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        import traceback
        tb = traceback.format_exc()
        app.logger.error(f"Unhandled Exception: {e}\n{tb}")
        if request.path.startswith("/api/"):
            return jsonify({"error": "An unexpected error occurred on the server.", "details": str(e)}), 500
        return f"<h1>Internal Server Error</h1><p>{str(e)}</p>", 500

    return app
