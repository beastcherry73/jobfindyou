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

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Browsers ignore HSTS over plain HTTP, and sending it in local dev
        # would pin localhost to https, so it is production-only.
        if os.environ.get("VERCEL"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Honest note on this CSP: the workspace SPA is thousands of lines of
        # INLINE script and style, so 'unsafe-inline' has to stay until that
        # is externalised or nonced. That means this policy does NOT stop an
        # injected inline payload -- escaping at the render site is still the
        # real defence. What it does buy is a origin allowlist: injected
        # markup cannot pull code from, or beacon data out to, a domain that
        # is not listed here.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )
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
        from markupsafe import escape
        tb = traceback.format_exc()
        app.logger.error(f"Unhandled Exception: {e}\n{tb}")

        # Exception text routinely carries driver messages, SQL fragments,
        # hostnames and filesystem paths, so it is not public information.
        # It used to be returned unconditionally because Vercel's runtime
        # logs need CLI auth, which made the response body the only way to
        # see a real traceback. That workflow is preserved behind a flag:
        # set DEBUG_ERRORS=1 in the environment to get the detail back while
        # diagnosing, and unset it afterwards. Default is now quiet.
        expose = os.environ.get("DEBUG_ERRORS") == "1"
        if request.path.startswith("/api/"):
            payload = {"error": "An unexpected error occurred on the server."}
            if expose:
                payload["details"] = str(e)
            return jsonify(payload), 500
        # escape(): without it any attacker-influenced text inside the
        # exception message is reflected into the page as live markup.
        detail = f"<p>{escape(str(e))}</p>" if expose else ""
        return f"<h1>Internal Server Error</h1>{detail}", 500

    return app
