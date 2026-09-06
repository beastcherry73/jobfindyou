import os
import secrets
from dotenv import load_dotenv

load_dotenv()

_DEV_SECRET = "change-this-local-development-secret"


def _is_vercel():
    return bool(os.environ.get("VERCEL"))


def configure_app(app):
    # SECRET_KEY signs the session cookie, so a known value means anyone can
    # forge a session for any user. The development default is committed to a
    # public repo, so it must NEVER be the key in production. If the env var
    # is missing there we fall back to a random per-instance key instead:
    # that logs everyone out whenever an instance recycles (visible, annoying,
    # recoverable) rather than silently shipping a publicly known signing key
    # (invisible, and full account takeover). It deliberately does not raise,
    # because taking the live site down over this would be the worse failure.
    _secret = os.environ.get("SECRET_KEY")
    if _is_vercel() and not _secret:
        app.logger.error(
            "STARTUP BLOCKER: SECRET_KEY is not set in production. Falling back "
            "to a random per-instance key, so sessions will not survive an "
            "instance recycle and users will be logged out unpredictably. "
            "Set SECRET_KEY in the Vercel project env and redeploy."
        )
        _secret = secrets.token_hex(32)
    app.config["SECRET_KEY"] = _secret or _DEV_SECRET

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.environ.get("VERCEL") or not os.access(BASE_DIR, os.W_OK):
        app.config["DATABASE"] = "/tmp/resumeai.db"
    else:
        app.config["DATABASE"] = os.path.join(BASE_DIR, "resumeai.db")

    app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
    app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
    if os.environ.get("VERCEL"):
        default_redirect = "https://www.jobspike.in/auth/google/callback"
    else:
        default_redirect = "http://localhost:5000/auth/google/callback"
    app.config["GOOGLE_REDIRECT_URI"] = os.environ.get("GOOGLE_REDIRECT_URI", default_redirect)

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))
    app.config["SESSION_COOKIE_NAME"] = "session"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400
    app.config["MAX_CONTENT_LENGTH"] = 11 * 1024 * 1024

    # Production DB validation (safe: never logs the connection string/credentials).
    if _is_vercel():
        pg_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
        db_env = "SUPABASE_DB_URL" if os.environ.get("SUPABASE_DB_URL") else "DATABASE_URL"
        if not pg_url:
            app.logger.error(
                "STARTUP BLOCKER: Neither SUPABASE_DB_URL nor DATABASE_URL is set. "
                "Vercel production REQUIRES PostgreSQL. SQLite is forbidden. "
                "Set SUPABASE_DB_URL in Vercel project env and redeploy."
            )
        else:
            scheme = pg_url.split("://", 1)[0] if "://" in pg_url else pg_url[:8]
            # Host/project identifier only — never credentials or the full URL.
            from backend.database import safe_parse_db_url
            parsed = safe_parse_db_url(pg_url)
            host = parsed.hostname
            project = (parsed.path or "").lstrip("/").split("/")[0] or None
            app.logger.info(
                f"Database env var present ({db_env}, scheme={scheme}), "
                f"host={host}, project={project}"
            )

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        from groq import Groq
        app.config["GROQ_CLIENT"] = Groq(api_key=groq_key)
    else:
        app.config["GROQ_CLIENT"] = None
