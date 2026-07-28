# JobSpike (Resume Analyzer) — Project Handover & Action Plan for Claude

> **Target Goal:** Fix Vercel Deployment, Configure OmniRoute Stack, Establish V1.0 MVP, and Redesign UI.  
> **Target Domain:** [https://www.jobspike.in](https://www.jobspike.in)

---

## 1. Executive Summary & Context

JobSpike is an AI-powered resume analysis, ATS scoring, and resume optimization web application built with Python Flask, Groq API (Llama 3.3 70B), and PyPDF.

The goal for today's session is to:
1. **Fix the Vercel 500 / Runtime Error** so [jobspike.in](https://www.jobspike.in) is live and functional.
2. **Standardize the AI Stack** using OmniRoute as a unified local routing proxy (`http://localhost:20128/v1`) with fallbacks across Groq, Gemini, NVIDIA, OpenRouter, and Cerebras.
3. **Lock down the MVP scope** (Google Login, Resume Upload, ATS Score, AI Suggestions, Resume Rewrite, PDF/Docx Download).
4. **Redesign the Landing Page** to match modern SaaS aesthetics.
5. **Establish persistent project documentation** (`PROJECT.md`, `TODO.md`, `BUGS.md`, `CHANGELOG.md`).

---

## 2. Codebase Overview & File Map

```
Resume analyzer/
├── api/
│   └── index.py            # Vercel serverless entry point (exports Flask app as handler)
├── templates/              # HTML templates (index.html, login.html, register.html, dashboard.html, etc.)
├── app.py                  # Main Flask application (1200+ lines: routes, ATS prompts, DB handlers)
├── generate_mock_resume.py # Test script for creating sample resumes
├── vercel.json             # Vercel configuration (serverless function route rewrite)
├── requirements.txt        # Python dependencies
├── resumeai.db / jobfindyou.db # Local SQLite databases
└── .env                    # Local environment variables (GROQ_API_KEY, SECRET_KEY, etc.)
```

---

## 3. Deep-Dive: Vercel Deployment & Runtime Errors

### Root Cause 1: In-Memory SQLite Anti-Pattern on Vercel
In `app.py` lines 322–367:
```python
def get_db():
    if os.environ.get("VERCEL"):
        db = sqlite3.connect(":memory:", timeout=30.0)
        # creates tables on the fly
        return db
```
**Why this breaks on Vercel:**
* Vercel Serverless Functions execute as stateless Lambda instances.
* `:memory:` creates an in-memory SQLite database *per request connection*.
* As soon as a request finishes, the connection closes and the memory is wiped completely.
* When a user registers or logs in, the user record is stored in memory and immediately lost. Subsequent requests (e.g. `/dashboard`, `/upload`) return 500 internal server errors or redirection loops because `SELECT * FROM users WHERE id = ?` returns no result.

**Recommended Fix Options:**
* **Option A (Quickest - Cloud DB):**
  Use a hosted database like **Supabase (PostgreSQL)**, **Turso (Serverless SQLite / libsql)**, or **Neon (Postgres)** via environment variables (`DATABASE_URL`).
* **Option B (SQLite File in `/tmp`):**
  Use `/tmp/resumeai.db` or PostgreSQL (`psycopg2-binary` / `SQLAlchemy`).

### Root Cause 2: Missing or Unconfigured Vercel Environment Variables
Ensure the following variables are set in the **Vercel Project Settings -> Environment Variables**:
* `SECRET_KEY` – Flask session signing key (must be a static long secret string).
* `GROQ_API_KEY` – API key for Groq (Llama 3.3 70B model execution).
* `GOOGLE_CLIENT_ID` – OAuth client ID.
* `GOOGLE_CLIENT_SECRET` – OAuth client secret.
* `GOOGLE_REDIRECT_URI` – Set to `https://www.jobspike.in/auth/google/callback`.

### Root Cause 3: Function Handler & Dependencies in `vercel.json`
* Check `requirements.txt`: ensure all dependencies used in `app.py` (e.g. `groq`, `pypdf`, `python-docx`, `flask`, `requests`, `python-dotenv`) are listed.
* In `vercel.json`, ensure static assets and templates are correctly routed:
```json
{
  "version": 2,
  "functions": {
    "api/index.py": {
      "includeFiles": "templates/**,static/**"
    }
  },
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/api/index.py"
    }
  ]
}
```

---

## 4. OmniRoute AI Stack Integration Guide

### OmniRoute Setup Parameters
* **Gateway URL:** `http://localhost:20128/v1`
* **Local Dashboard:** `http://localhost:20128`

### Step-by-Step Tooling Plan:
1. **Connect Providers:**
   - Groq API Key
   - Gemini API Key
   - NVIDIA / OpenRouter / Cerebras API Keys
2. **Create Coding Combo:**
   - Define a fallback combo in OmniRoute (e.g., `auto/coding` or `auto/smart` balancing speed, context fit, and rate limits).
3. **Configure Editors (Antigravity & OpenCode):**
   - Point OpenCode & Antigravity IDE model base URLs to `http://localhost:20128/v1`.
   - Set bearer token to OmniRoute client token generated from the dashboard.

---

## 5. Scope Definition: JobSpike MVP 1.0

Do **NOT** add extra features until these 6 core user stories pass testing:

- [ ] **Google Login / Email Auth:** Seamless user login and session handling.
- [ ] **Upload Resume:** PDF & DOCX file upload parser.
- [ ] **Resume Score & ATS Breakdown:** Comprehensive ATS readiness metrics.
- [ ] **AI Suggestions:** Actionable feedback (missing keywords, passive bullet replacements).
- [ ] **Resume Rewrite / Polish:** One-click AI rewrite retaining true user metrics.
- [ ] **Download Resume:** Export polished resume as PDF or formatted DOCX.

---

## 6. Action Items Checklist for Claude / Developer

### Step 1: Repair Vercel Deployment
- [ ] Update `app.py` database connection to use a persistent database (Turso or Supabase / Postgres) or cloud connection string instead of ephemeral `:memory:`.
- [ ] Add exception handling and detailed logging around `call_groq()` and PDF parsing in `app.py`.
- [ ] Verify `requirements.txt` has `psycopg2-binary` or `libsql-client` if switching databases.
- [ ] Test Vercel build locally via `vercel dev` command.

### Step 2: Create Core Project Files
Generate the following files in the project root:
1. `PROJECT.md` – High-level architecture, setup instructions, stack breakdown.
2. `TODO.md` – Active task tracker for MVP V1.0.
3. `BUGS.md` – Active bug tracker (including Vercel deployment logs & fixes).
4. `CHANGELOG.md` – Log of updates and fixes.

### Step 3: UI Modernization
- [ ] Inspect existing `templates/index.html`.
- [ ] Redesign landing page with modern SaaS layout (dark mode option, gradient accents, hero section with live demo card, testimonial/stats counter).

---

## 7. Verification Steps

1. Run `python app.py` locally to confirm 200 OK on home, login, and dashboard routes.
2. Run `vercel dev` to simulate serverless environment.
3. Deploy to Vercel via `git push` or `vercel --prod`.
4. Verify HTTPS access at [https://www.jobspike.in](https://www.jobspike.in).
