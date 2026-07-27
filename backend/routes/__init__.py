from .static import static_bp
from .auth import auth_bp
from .analysis import analysis_bp
from .builder import builder_bp
from .generate import generate_bp
from .export import export_bp


def register_blueprints(app):
    app.register_blueprint(static_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(export_bp)
