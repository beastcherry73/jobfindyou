import os
from flask import Flask, request, jsonify
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

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        import traceback
        tb = traceback.format_exc()
        app.logger.error(f"Unhandled Exception: {e}\n{tb}")
        if request.path.startswith("/api/"):
            return jsonify({"error": "An unexpected error occurred on the server.", "details": str(e)}), 500
        return f"<h1>Internal Server Error</h1><p>{str(e)}</p>", 500

    return app
