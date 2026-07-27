import os
from dotenv import load_dotenv

load_dotenv()


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

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        from groq import Groq
        app.config["GROQ_CLIENT"] = Groq(api_key=groq_key)
    else:
        app.config["GROQ_CLIENT"] = None
