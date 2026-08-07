import secrets
import logging
import requests as http_requests
from urllib.parse import urlencode
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, flash, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from backend.database import get_db, store_oauth_state, verify_oauth_state, cleanup_expired_oauth_states
from backend.decorators import login_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
@auth_bp.route("/auth/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("static_routes.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("Please complete every field.", "error")
        elif len(password) < 8:
            flash("Choose a password with at least 8 characters.", "error")
        else:
            try:
                with get_db() as db:
                    cursor = db.execute(
                        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                        (name, email, generate_password_hash(password))
                    )
                    user_id = cursor.lastrowid
                session.clear()
                session["user_id"] = user_id
                session["user_name"] = name
                return redirect(url_for("static_routes.index"))
            except Exception as e:
                if "UNIQUE" in str(e) or "IntegrityError" in str(e):
                    flash("An account already exists for that email.", "error")
                else:
                    flash("Registration failed. Please try again.", "error")
    return render_template("auth.html", mode="register")


@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/auth/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("static_routes.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("static_routes.index"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")


@auth_bp.route("/auth/google")
def google_login():
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI")
    logger.info(f"OAuth login initiated — client_id configured: {bool(client_id)}, redirect_uri: {redirect_uri}")

    if not client_id or not client_secret:
        logger.warning("Google OAuth not configured — missing client_id or client_secret")
        flash("Google sign-in is not configured yet. Add the Google client ID and secret to .env.", "error")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    store_oauth_state(state)

    session["google_oauth_state"] = state

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    logger.info(f"Redirecting to Google OAuth — state stored in DB + session, url: {auth_url[:80]}...")
    return redirect(auth_url)


@auth_bp.route("/auth/google/callback")
def google_callback():
    callback_state = request.args.get("state", "")
    callback_code = request.args.get("code", "")
    callback_error = request.args.get("error", "")
    logger.info(f"OAuth callback received — state present: {bool(callback_state)}, code present: {bool(callback_code)}, error: {callback_error or 'none'}")

    session_state = session.pop("google_oauth_state", None)
    logger.info(
        f"OAuth state from session: {'PRESENT' if session_state else 'MISSING (null)'} "
        f"(expected: {callback_state[:16] if callback_state else 'N/A'}...) "
        f"(session: {session_state[:16] if session_state else 'N/A'}...)"
    )

    db_valid = verify_oauth_state(callback_state)
    logger.info(f"OAuth state from database: {'VALID' if db_valid else 'INVALID or MISSING'}")

    if not db_valid:
        logger.warning(
            f"OAuth state verification FAILED — state not found in database. "
            f"This is the ROOT CAUSE: the session cookie was carried by the request, "
            f"but the OAuth state was never stored in the database, or it expired. "
            f"Session state was {'present' if session_state else 'NOT present'}."
        )

    if not db_valid and session_state != callback_state:
        logger.error(f"OAuth state mismatch. Session: {session_state}, Callback: {callback_state[:16]}..., DB valid: {db_valid}")
        flash("Google sign-in could not be verified. Please try again.", "error")
        return redirect(url_for("auth.login"))

    if callback_error or not callback_code:
        logger.info(f"OAuth cancelled or missing code — error: {callback_error}")
        flash("Google sign-in was cancelled.", "error")
        return redirect(url_for("auth.login"))

    try:
        token_response = http_requests.post("https://oauth2.googleapis.com/token", data={
            "code": callback_code,
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
            "grant_type": "authorization_code",
        }, timeout=10)
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        logger.info("Google OAuth token exchange succeeded")

        profile_response = http_requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
        logger.info(f"Google profile fetched — sub: {profile.get('sub', 'N/A')[:8]}..., email_verified: {profile.get('email_verified')}")

        if not profile.get("email_verified"):
            raise ValueError("Google did not return a verified email address.")
        google_sub, email = profile["sub"], profile["email"].lower()
        name = profile.get("name") or email.split("@")[0]

        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE google_sub = ? OR email = ?", (google_sub, email)).fetchone()
            if user:
                db.execute("UPDATE users SET google_sub = ? WHERE id = ?", (google_sub, user["id"]))
                user_id, user_name = user["id"], user["name"]
                logger.info(f"Existing user logged in via Google — id: {user_id}")
            else:
                cursor = db.execute(
                    "INSERT INTO users (name, email, password_hash, google_sub) VALUES (?, ?, ?, ?)",
                    (name, email, generate_password_hash(secrets.token_urlsafe(32)), google_sub)
                )
                user_id, user_name = cursor.lastrowid, name
                logger.info(f"New user created via Google — id: {user_id}")

        session.clear()
        session.permanent = True
        session["user_id"], session["user_name"] = user_id, user_name
        logger.info(f"Session created for user {user_id}, redirecting to index")
        cleanup_expired_oauth_states()
        return redirect(url_for("static_routes.index"))

    except (http_requests.RequestException, KeyError, ValueError) as error:
        logger.error(f"Google OAuth flow failed: {error}")
        flash(f"Google sign-in failed: {error}", "error")
        return redirect(url_for("auth.login"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/api/user/profile", methods=["GET", "PUT"])
@login_required
def user_profile():
    user_id = session.get("user_id")
    with get_db() as db:
        if request.method == "GET":
            user = db.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return jsonify({"error": "User not found"}), 404
            count_row = db.execute("SELECT COUNT(*) as cnt FROM analyses WHERE user_id = ?", (user_id,)).fetchone()
            analysis_count = 0
            if count_row:
                analysis_count = count_row.get("cnt") if hasattr(count_row, "get") else count_row[0]
            return jsonify({
                "user": dict(user),
                "total_analyses": analysis_count or 0
            })
        else:
            data = request.get_json() or {}
            new_name = data.get("name", "").strip()
            new_password = data.get("password", "")
            if new_name:
                db.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, user_id))
                session["user_name"] = new_name
            if new_password and len(new_password) >= 8:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), user_id))
            db.commit()
            return jsonify({"message": "Profile updated successfully"})
