import logging

from flask import Blueprint, render_template, Response, session, redirect

from backend.database import get_db
from backend.guides import GUIDES

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


def _sitemap_url(path, changefreq, priority, lastmod=""):
    mod = f"\n    <lastmod>{lastmod}</lastmod>" if lastmod else ""
    return (f"  <url>\n    <loc>https://www.jobspike.in{path}</loc>{mod}\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n  </url>")


@static_bp.route("/sitemap.xml")
def sitemap():
    urls = [
        _sitemap_url("/", "daily", "1.0"),
        _sitemap_url("/guides", "weekly", "0.9"),
        _sitemap_url("/compare/resumax", "monthly", "0.7"),
        _sitemap_url("/login", "monthly", "0.8"),
        _sitemap_url("/register", "monthly", "0.8"),
    ]
    urls += [_sitemap_url(f"/guides/{g['slug']}", "monthly", "0.8", g["updated"]) for g in GUIDES]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>")
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

