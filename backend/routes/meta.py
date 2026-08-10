from flask import Blueprint, jsonify
from backend.database import db_diagnostic

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/api/health/db")
def db_health():
    """Safe database diagnostic endpoint.

    Reports only:
    - database backend (PostgreSQL / SQLite)
    - whether the required DB env var exists (boolean, NOT the value)
    - database host / project identifier derived from the URL (no credentials)
    """
    return jsonify(db_diagnostic())


@meta_bp.route("/api/health")
def health():
    return jsonify({"status": "ok"})