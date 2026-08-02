from functools import wraps
from flask import session, request, jsonify, redirect, url_for


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in to use ResumeAI."}), 401
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped_view
