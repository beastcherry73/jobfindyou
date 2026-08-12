import os
from dotenv import load_dotenv

load_dotenv()


def _is_vercel():
    return bool(os.environ.get("VERCEL"))


def configure_app(app):
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-local-development-secret")

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
