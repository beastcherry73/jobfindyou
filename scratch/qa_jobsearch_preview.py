"""Local-only authenticated preview for responsive job-search QA.

Never import this from production. It exists solely to make the signed-in
workspace searchable in a local, disposable browser session.
"""
import os
import sys

from flask import render_template, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app


app = create_app()


@app.get("/__qa/jobsearch")
def jobsearch_preview():
    session["user_id"] = 1
    session["user_name"] = "QA reviewer"
    return render_template("workspace.html", user_name="QA reviewer",
                           initial_section="jobsearch")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
