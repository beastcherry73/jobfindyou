import os
import sys
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from app import app
except Exception as exc:
    _boot_error = (type(exc).__name__, str(exc), traceback.format_exc())

    def app(environ, start_response):
        err_type, err_msg, tb = _boot_error
        body = (
            f"STARTUP ERROR: {err_type}: {err_msg}\n\n{tb}"
        ).encode("utf-8", "replace")
        start_response(
            "500 Internal Server Error",
            [("Content-Type", "text/plain; charset=utf-8")],
        )
        return [body]


handler = app
application = app
