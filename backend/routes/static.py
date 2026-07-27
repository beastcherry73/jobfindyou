from flask import Blueprint, render_template, Response, session

static_bp = Blueprint("static_routes", __name__)


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
def index():
    is_authenticated = "user_id" in session
    user_name = session.get("user_name", "there")
    if is_authenticated:
        return render_template("workspace.html", user_name=user_name)
    return render_template("index.html", is_authenticated=is_authenticated, user_name=user_name)
