import time
from functools import wraps
from flask import request, jsonify, session
from backend.database import get_db


def client_ip():
    """The real client IP, correcting for the fact that we run behind a proxy.

    On Vercel `request.remote_addr` is the platform's own edge address, not
    the caller: keying on it lumps every anonymous visitor into ONE bucket,
    so a guest limit either locks out the world at once or does nothing.

    `x-vercel-forwarded-for` is set by Vercel itself and overwrites whatever
    the client sent, so it cannot be forged. Plain `x-forwarded-for` can be:
    a client may send its own value which the proxy then appends to, so the
    LEFTMOST entries are attacker-controlled and only the RIGHTMOST hop --
    the one our nearest trusted proxy added -- can be believed.
    """
    vercel_ip = request.headers.get("X-Vercel-Forwarded-For")
    if vercel_ip:
        return vercel_ip.split(",")[0].strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "anonymous"


def _rate_key():
    return str(session.get("user_id") or client_ip())


def rate_limit(limit, window_seconds, key_fn=None, on_limit=None, methods=None):
    """Simple fixed-window rate limit backed by the app database.

    Counts requests per key (user id, or IP for guests) within a time
    window and rejects with 429 once the limit is exceeded. Fails open:
    if the rate-limit infra itself errors, the request proceeds so we
    never break the app over a safety feature.

    `on_limit` lets a form-rendering route answer with HTML instead of the
    default JSON body, which would otherwise dump a raw JSON blob in front
    of someone who simply mistyped their password a few times.

    `methods` restricts counting to specific HTTP verbs. The auth routes
    serve their form on GET and act on POST from the SAME url, so counting
    every request meant simply LOADING the signup page ~10 times in an hour
    locked a real person out of a page they had not even submitted yet.
    Defaults to None (count everything), which keeps the GET-only API
    routes -- /api/jobs/search and friends -- limited as before.
    """

    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if methods and request.method not in methods:
                return view(*args, **kwargs)
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
                        if on_limit:
                            return on_limit(retry_after)
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
