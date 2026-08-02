import time
from functools import wraps
from flask import request, jsonify, session
from backend.database import get_db


def _rate_key():
    return str(session.get("user_id") or request.remote_addr or "anonymous")


def rate_limit(limit, window_seconds, key_fn=None):
    """Simple fixed-window rate limit backed by the app database.

    Counts requests per key (user id, or IP for guests) within a time
    window and rejects with 429 once the limit is exceeded. Fails open:
    if the rate-limit infra itself errors, the request proceeds so we
    never break the app over a safety feature.
    """

    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            key = key_fn() if key_fn else _rate_key()
            now = int(time.time())
            window_start = (now // window_seconds) * window_seconds

            try:
                with get_db() as db:
                    db.execute(
                        """INSERT INTO rate_limits (key, window_start, hits) VALUES (?, ?, 1)
                           ON CONFLICT(key, window_start) DO UPDATE SET hits = hits + 1""",
                        (key, window_start)
                    )
                    row = db.execute(
                        "SELECT hits FROM rate_limits WHERE key = ? AND window_start = ?",
                        (key, window_start)
                    ).fetchone()
                    hits = row["hits"] if row else 1
                    db.commit()
                    if hits > limit:
                        retry_after = max(0, (window_start + window_seconds) - now)
                        resp = jsonify({"error": f"Too many requests. Please try again in {retry_after} seconds."})
                        resp.status_code = 429
                        return resp
            except Exception:
                pass

            # Lightweight periodic cleanup of expired windows
            if (now // 60) % 7 == 0:
                try:
                    with get_db() as db:
                        db.execute(
                            "DELETE FROM rate_limits WHERE window_start < ?",
                            (now - 2 * window_seconds,)
                        )
                        db.commit()
                except Exception:
                    pass

            return view(*args, **kwargs)
        return wrapped_view
    return decorator
