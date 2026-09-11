import logging

from flask import Blueprint, render_template, Response, session, redirect

from backend.database import get_db

static_bp = Blueprint("static_routes", __name__)
logger = logging.getLogger(__name__)


def _workspace_boot(user_id):
    """Data embedded in the workspace page so its first paint needs no API call.

    Just the analyses LIST -- the same narrow columns GET /api/analyses
    returns. The dashboard used to render, then fetch this, then fetch the
    latest report: two serial round trips before anything useful appeared,
    for rows the server could have sent with the page. Best-effort: any
    failure returns None and the page falls back to fetching as before.
    """
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT id, filename, overall_score, summary, created_at FROM analyses "
                "WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return {"analyses": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning(f"Workspace boot data unavailable: {e}")
        return None


@static_bp.route("/favicon.ico")
def favicon():
    return "", 204


@static_bp.route("/robots.txt")
def robots():
    content = "User-agent: *\nAllow: /\nSitemap: https://www.jobspike.in/sitemap.xml"
    return Response(content, mimetype="text/plain")


@static_bp.route("/sitemap.xml")
def sitemap():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.jobspike.in/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://www.jobspike.in/login</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://www.jobspike.in/register</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
    return Response(xml, mimetype="application/xml")


@static_bp.route("/")
@static_bp.route("/workspace")
@static_bp.route("/dashboard")
@static_bp.route("/analysis")
@static_bp.route("/builder")
@static_bp.route("/improve")
@static_bp.route("/tracker")
@static_bp.route("/profile")
@static_bp.route("/settings")
@static_bp.route("/billing")
def index():
    is_authenticated = "user_id" in session
    user_name = session.get("user_name", "there")
    if is_authenticated:
        return render_template("workspace.html", user_name=user_name,
                               boot=_workspace_boot(session["user_id"]))
    return render_template("index.html", is_authenticated=is_authenticated, user_name=user_name)

