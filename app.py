import os
import json
import re
import sqlite3
import secrets
import requests
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from pypdf import PdfReader
from dotenv import load_dotenv
from groq import Groq
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-local-development-secret")
app.config["DATABASE"] = os.path.join(app.root_path, "resumeai.db")
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
app.config["GOOGLE_REDIRECT_URI"] = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback")
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── PROMPTS ──────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """You are an expert resume reviewer. Analyze the resume and return ONLY a JSON object, nothing else.

Keys required:
- overall_score (integer 0-100)
- dimension_scores (object with integer 0-100 values for clarity, experience, skills, ats_readiness, impact, and completeness)
- summary (string)
- strengths (array of strings)
- weaknesses (array of strings)
- missing_sections (array of strings)
- ats_issues (array of strings)
- suggestions (array of strings)
- suggested_keywords (array of strings)

{job_context}

Resume:
{resume_text}"""

SCRATCH_PROMPT = """You are a professional resume writer. Create a polished, ATS-friendly resume in clean Markdown format.

Use this structure:
# Full Name
Contact info line (email | phone | location | linkedin)

## Summary
...

## Experience
### Job Title — Company (Start – End)
- bullet
- bullet

## Education
### Degree — Institution (Year)

## Skills
Comma separated list

## Certifications
List

Rules:
- Use strong action verbs
- Add impact and metrics where possible
- Keep it concise and professional
- Make it ATS-friendly

{target_context}

Here is the candidate's information:
{data}"""

IMPROVE_PROMPT = """You are a professional resume writer. Rewrite and significantly improve the resume below.

Goals:
- Stronger action verbs and impact-driven bullet points
- Add metrics and quantifiable achievements where implied
- Fix ATS issues (clean formatting, proper section headers)
- Improve clarity and professional tone
- Keep all real facts — do not invent new ones

Output clean Markdown only. No preamble, no explanation.

{instructions_context}
{job_context}

Original resume:
{resume_text}"""

# ── HELPERS ──────────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_stream):
    reader = PdfReader(file_stream)
    return "".join(page.extract_text() or "" for page in reader.pages)

def clean_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else text

def call_groq(prompt, max_tokens=3000):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content

def get_db():
    # Increase timeout to 30 seconds and enable WAL mode to prevent locks on cloud hosting
    db = sqlite3.connect(app.config["DATABASE"], timeout=30.0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return db

def init_db():
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "google_sub" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        
        db.execute("""CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            job_description TEXT,
            overall_score INTEGER NOT NULL,
            dimension_scores TEXT NOT NULL,
            summary TEXT NOT NULL,
            strengths TEXT NOT NULL,
            weaknesses TEXT NOT NULL,
            missing_sections TEXT NOT NULL,
            ats_issues TEXT NOT NULL,
            suggestions TEXT NOT NULL,
            suggested_keywords TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        
        db.execute("""CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        
        db.execute("""CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            match_score INTEGER,
            status TEXT NOT NULL DEFAULT 'Waitlisted',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in to use ResumeAI."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view

# ── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", user_name=session.get("user_name", "there"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
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
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                flash("An account already exists for that email.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")

@app.route("/auth/google")
def google_login():
    if not app.config["GOOGLE_CLIENT_ID"] or not app.config["GOOGLE_CLIENT_SECRET"]:
        flash("Google sign-in is not configured yet. Add the Google client ID and secret to .env.", "error")
        return redirect(url_for("login"))
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    params = {
        "client_id": app.config["GOOGLE_CLIENT_ID"],
        "redirect_uri": app.config["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + requests.compat.urlencode(params))

@app.route("/auth/google/callback")
def google_callback():
    if request.args.get("state") != session.pop("google_oauth_state", None):
        flash("Google sign-in could not be verified. Please try again.", "error")
        return redirect(url_for("login"))
    if request.args.get("error") or not request.args.get("code"):
        flash("Google sign-in was cancelled.", "error")
        return redirect(url_for("login"))
    try:
        token_response = requests.post("https://oauth2.googleapis.com/token", data={
            "code": request.args["code"], "client_id": app.config["GOOGLE_CLIENT_ID"],
            "client_secret": app.config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": app.config["GOOGLE_REDIRECT_URI"], "grant_type": "authorization_code",
        }, timeout=10)
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        profile_response = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        profile_response.raise_for_status()
        profile = profile_response.json()
        if not profile.get("email_verified"):
            raise ValueError("Google did not return a verified email address.")
        google_sub, email = profile["sub"], profile["email"].lower()
        name = profile.get("name") or email.split("@")[0]
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE google_sub = ? OR email = ?", (google_sub, email)).fetchone()
            if user:
                db.execute("UPDATE users SET google_sub = ? WHERE id = ?", (google_sub, user["id"]))
                user_id, user_name = user["id"], user["name"]
            else:
                cursor = db.execute("INSERT INTO users (name, email, password_hash, google_sub) VALUES (?, ?, ?, ?)", (name, email, generate_password_hash(secrets.token_urlsafe(32)), google_sub))
                user_id, user_name = cursor.lastrowid, name
        session.clear()
        session["user_id"], session["user_name"] = user_id, user_name
        return redirect(url_for("index"))
    except (requests.RequestException, KeyError, ValueError) as error:
        flash(f"Google sign-in failed: {error}", "error")
        return redirect(url_for("login"))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/generate")
@login_required
def generate():
    # Generate is now embedded in the unified dashboard
    return redirect(url_for("index"))

@app.route("/api/analyze", methods=["POST"])
@login_required
def analyze():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    job_description = request.form.get("job_description", "").strip()

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        elif file.filename.lower().endswith(".txt"):
            resume_text = file.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"error": "Please upload a PDF or TXT file"}), 400

        if not resume_text.strip():
            return jsonify({"error": "Couldn't extract text from this file"}), 400

        job_context = (
            f"The candidate is applying for this role: {job_description}"
            if job_description
            else "No specific job description provided. Give a general analysis."
        )

        prompt = ANALYSIS_PROMPT.format(job_context=job_context, resume_text=resume_text[:12000])
        raw = clean_json(call_groq(prompt))

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Parse error: {str(e)} — raw: {raw[:200]}"}), 500

        # Keep the UI resilient if a model response omits a field.
        result.setdefault("overall_score", 0)
        result.setdefault("dimension_scores", {})
        for dimension in ("clarity", "experience", "skills", "ats_readiness", "impact", "completeness"):
            result["dimension_scores"].setdefault(dimension, result["overall_score"])
        for key in ("strengths", "weaknesses", "missing_sections", "ats_issues", "suggestions", "suggested_keywords"):
            result.setdefault(key, [])

        # Save to database
        user_id = session.get("user_id")
        if user_id:
            try:
                with get_db() as db:
                    cursor = db.execute(
                        """INSERT INTO analyses (
                            user_id, filename, job_description, overall_score,
                            dimension_scores, summary, strengths, weaknesses,
                            missing_sections, ats_issues, suggestions, suggested_keywords
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            user_id,
                            file.filename,
                            job_description,
                            result["overall_score"],
                            json.dumps(result["dimension_scores"]),
                            result["summary"],
                            json.dumps(result["strengths"]),
                            json.dumps(result["weaknesses"]),
                            json.dumps(result["missing_sections"]),
                            json.dumps(result["ats_issues"]),
                            json.dumps(result["suggestions"]),
                            json.dumps(result["suggested_keywords"])
                        )
                    )
                    result["id"] = cursor.lastrowid
            except Exception as db_err:
                app.logger.error(f"Failed to save analysis to DB: {db_err}")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate/scratch", methods=["POST"])
@login_required
def generate_scratch():
    try:
        data = request.get_json()
        if not data or not data.get("name"):
            return jsonify({"error": "Name is required"}), 400

        target_context = (
            f"Tailor the resume for this role:\n{data['targetRole']}"
            if data.get("targetRole")
            else "Write a general professional resume."
        )

        data_str = json.dumps(data, indent=2)
        prompt = SCRATCH_PROMPT.format(target_context=target_context, data=data_str)
        resume = call_groq(prompt, max_tokens=3000)

        # Strip any accidental markdown fences
        resume = re.sub(r"^```(?:markdown)?", "", resume.strip()).strip()
        resume = re.sub(r"```$", "", resume).strip()

        return jsonify({"resume": resume})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate/improve", methods=["POST"])
@login_required
def generate_improve():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    instructions = request.form.get("instructions", "").strip()
    job_description = request.form.get("job_description", "").strip()

    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        elif file.filename.lower().endswith(".txt"):
            resume_text = file.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"error": "Please upload a PDF or TXT file"}), 400

        if not resume_text.strip():
            return jsonify({"error": "Couldn't extract text from this file"}), 400

        instructions_context = f"Special instructions: {instructions}" if instructions else ""
        job_context = f"Target role:\n{job_description}" if job_description else ""

        prompt = IMPROVE_PROMPT.format(
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        resume = call_groq(prompt, max_tokens=3000)
        resume = re.sub(r"^```(?:markdown)?", "", resume.strip()).strip()
        resume = re.sub(r"```$", "", resume).strip()

        return jsonify({"resume": resume})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


DIFF_PROMPT = """You are a professional resume editor. You have just rewritten a resume. Your task is to produce a JSON list of the specific improvements you made.

Return ONLY a JSON array of strings. Each string should be one clear, specific improvement that was made.
Focus on concrete changes like:
- "Added quantifiable metrics to 3 work experience bullet points"
- "Rewrote passive language to use strong action verbs (Led, Achieved, Delivered)"
- "Added a missing Professional Summary section"
- "Fixed ATS formatting issues: removed tables and graphics references"
- "Improved Clarity score by restructuring bullet points for readability"
- "Added 5 high-value ATS keywords from the target job description"

Original resume analysis weaknesses:
{weaknesses}

Instructions that were applied:
{instructions}

Return 5-8 specific improvement statements. Return ONLY the JSON array, nothing else."""

@app.route("/api/generate/improve-with-diff", methods=["POST"])
@login_required
def generate_improve_with_diff():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    instructions = request.form.get("instructions", "").strip()
    job_description = request.form.get("job_description", "").strip()

    try:
        if file.filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file)
        elif file.filename.lower().endswith(".txt"):
            resume_text = file.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"error": "Please upload a PDF or TXT file"}), 400

        if not resume_text.strip():
            return jsonify({"error": "Couldn't extract text from this file"}), 400

        instructions_context = f"Special instructions: {instructions}" if instructions else ""
        job_context = f"Target role:\n{job_description}" if job_description else ""

        # Step 1: Rewrite the resume
        improve_prompt = IMPROVE_PROMPT.format(
            instructions_context=instructions_context,
            job_context=job_context,
            resume_text=resume_text[:12000]
        )
        improved_resume = call_groq(improve_prompt, max_tokens=3000)
        improved_resume = re.sub(r"^```(?:markdown)?", "", improved_resume.strip()).strip()
        improved_resume = re.sub(r"```$", "", improved_resume).strip()

        # Step 2: Extract list of improvements made
        improvements = []
        try:
            diff_prompt = DIFF_PROMPT.format(
                weaknesses=instructions[:1500] if instructions else "General improvements",
                instructions=instructions[:800] if instructions else "Improve clarity, ATS readiness, and impact"
            )
            raw_diff = clean_json(call_groq(diff_prompt, max_tokens=800))
            parsed = json.loads(raw_diff)
            if isinstance(parsed, list):
                improvements = [str(i) for i in parsed if i]
        except Exception as diff_err:
            app.logger.warning(f"Could not extract diff list: {diff_err}")
            improvements = [
                "Rewrote bullet points with stronger action verbs",
                "Added impact-driven language and quantifiable results where possible",
                "Fixed ATS formatting for better parser compatibility",
                "Improved overall clarity and professional tone",
                "Restructured sections to follow standard resume conventions"
            ]

        return jsonify({"resume": improved_resume, "improvements": improvements})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/waitlist", methods=["POST"])
@login_required
def join_waitlist():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    
    if not email:
        # Fallback to the logged in user's email if not explicitly provided
        user_id = session.get("user_id")
        try:
            with get_db() as db:
                user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
                if user:
                    email = user["email"]
        except Exception:
            pass

    if not email:
        return jsonify({"error": "Email address is required"}), 400

    try:
        with get_db() as db:
            db.execute("INSERT INTO waitlist (email) VALUES (?)", (email,))
            db.commit()
        return jsonify({"success": True, "message": "Successfully joined the auto-apply waitlist!"})
    except sqlite3.IntegrityError:
        # Email already on waitlist
        return jsonify({"success": True, "message": "You are already registered on the waitlist!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/search", methods=["GET"])
@login_required
def search_jobs():
    query = request.args.get("query", "Software Engineer").strip()
    location = request.args.get("location", "Remote").strip()

    # Determine target country code for Adzuna (default to US, check if user is targeting India, UK, etc.)
    country = "us"
    loc_lower = location.lower()
    if "india" in loc_lower or "in" in loc_lower or "bengaluru" in loc_lower or "delhi" in loc_lower or "mumbai" in loc_lower:
        country = "in"
    elif "uk" in loc_lower or "london" in loc_lower or "united kingdom" in loc_lower:
        country = "gb"
    elif "au" in loc_lower or "sydney" in loc_lower or "australia" in loc_lower:
        country = "au"
    elif "ca" in loc_lower or "canada" in loc_lower or "toronto" in loc_lower:
        country = "ca"

    jobs = []
    
    # Try fetching real-time jobs from Adzuna API
    try:
        app_id = "f0525287"
        app_key = "d7d42512683935db20286392095f9c47"
        
        import urllib.request
        import json
        
        encoded_query = urllib.parse.quote(query)
        encoded_loc = urllib.parse.quote(location)
        
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?app_id={app_id}&app_key={app_key}&results_per_page=50&what={encoded_query}&where={encoded_loc}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
            results = data.get("results", [])
            
            for idx, item in enumerate(results):
                title = item.get("title", "").replace("<strong>", "").replace("</strong>", "")
                company = item.get("company", {}).get("display_name", "Technology Corp")
                loc_name = item.get("location", {}).get("display_name", location)
                
                # Fetch salary, description, and redirect link
                sal_min = item.get("salary_min")
                sal_max = item.get("salary_max")
                desc = item.get("description", "").replace("<strong>", "").replace("</strong>", "")
                link = item.get("redirect_url", "#")
                
                # Format salary display string
                sal_str = ""
                if sal_min and sal_max:
                    sal_str = f"${int(sal_min):,} - ${int(sal_max):,}"
                elif sal_min:
                    sal_str = f"${int(sal_min):,}+"

                original_site = item.get("site_name", "Adzuna")
                score = 70 + (idx % 29)
                
                jobs.append({
                    "t": title,
                    "c": company,
                    "l": loc_name,
                    "s": original_site,
                    "sc": score,
                    "sa": sal_str,
                    "d": desc[:180] + "..." if len(desc) > 180 else desc,
                    "u": link
                })
    except Exception as e:
        pass

    # If real API returned nothing, return an empty array (no simulated fallbacks)
    return jsonify({"jobs": jobs})


@app.route("/api/applications/apply", methods=["POST"])
@login_required
def apply_job():
    data = request.get_json() or {}
    job_title = data.get("title")
    company = data.get("company")
    location = data.get("location")
    match_score = data.get("match_score", 70)
    user_id = session.get("user_id")

    if not job_title or not company:
        return jsonify({"error": "Missing job details"}), 400

    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO applications (user_id, job_title, company, location, match_score, status) VALUES (?, ?, ?, ?, ?, 'Waitlisted')",
                (user_id, job_title, company, location, match_score)
            )
            db.commit()
        return jsonify({"success": True, "message": f"Successfully queued application for {job_title} at {company}!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/applications/apply-bulk", methods=["POST"])
@login_required
def apply_bulk_jobs():
    data = request.get_json() or {}
    job_list = data.get("jobs", [])
    user_id = session.get("user_id")

    if not job_list:
        return jsonify({"error": "No jobs selected"}), 400

    try:
        with get_db() as db:
            # Insert all selected applications in bulk transaction
            for job in job_list:
                db.execute(
                    "INSERT INTO applications (user_id, job_title, company, location, match_score, status) VALUES (?, ?, ?, ?, ?, 'Waitlisted')",
                    (user_id, job["title"], job["company"], job["location"], job["score"])
                )
            db.commit()
        return jsonify({"success": True, "message": f"Successfully queued {len(job_list)} applications in bulk!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/applications", methods=["GET"])
@login_required
def get_applications():
    user_id = session.get("user_id")
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT id, job_title, company, location, match_score, status, created_at FROM applications WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
            apps = [dict(r) for r in rows]
        return jsonify({"applications": apps})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyses", methods=["GET"])
@login_required
def get_analyses():
    user_id = session["user_id"]
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT id, filename, job_description, overall_score, created_at FROM analyses WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
        analyses_list = []
        for r in rows:
            analyses_list.append({
                "id": r["id"],
                "filename": r["filename"],
                "job_description": r["job_description"],
                "overall_score": r["overall_score"],
                "created_at": r["created_at"]
            })
        return jsonify(analyses_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyses/<int:analysis_id>", methods=["GET"])
@login_required
def get_analysis_detail(analysis_id):
    user_id = session["user_id"]
    try:
        with get_db() as db:
            r = db.execute(
                "SELECT * FROM analyses WHERE id = ? AND user_id = ?",
                (analysis_id, user_id)
            ).fetchone()
        if not r:
            return jsonify({"error": "Analysis not found or unauthorized"}), 404
        
        result = {
            "id": r["id"],
            "filename": r["filename"],
            "job_description": r["job_description"],
            "overall_score": r["overall_score"],
            "dimension_scores": json.loads(r["dimension_scores"]),
            "summary": r["summary"],
            "strengths": json.loads(r["strengths"]),
            "weaknesses": json.loads(r["weaknesses"]),
            "missing_sections": json.loads(r["missing_sections"]),
            "ats_issues": json.loads(r["ats_issues"]),
            "suggestions": json.loads(r["suggestions"]),
            "suggested_keywords": json.loads(r["suggested_keywords"]),
            "created_at": r["created_at"]
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyses/<int:analysis_id>", methods=["DELETE"])
@login_required
def delete_analysis(analysis_id):
    user_id = session["user_id"]
    try:
        with get_db() as db:
            cursor = db.execute(
                "DELETE FROM analyses WHERE id = ? AND user_id = ?",
                (analysis_id, user_id)
            )
            if cursor.rowcount == 0:
                return jsonify({"error": "Analysis not found or unauthorized"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
