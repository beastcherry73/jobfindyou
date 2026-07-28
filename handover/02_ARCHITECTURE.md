# Architectural Documentation: JobSpike

This document defines the application architecture, repository structure, and key processing flows for authentication, resume parsing, and AI analysis.

---

## 1. Repository Directory Map
```
Resume analyzer/
├── .env                    # Local environment variables
├── requirements.txt        # Python package dependencies
├── vercel.json             # Vercel Serverless routing & file inclusions
├── app.py                  # Core application (routes, database configuration, analysis pipelines)
├── api/
│   └── index.py            # Vercel entrypoint (routes to root app)
├── templates/              # HTML layout files (index.html, login.html, dashboard.html, etc.)
├── static/                 # Static CSS, JS, and image assets (if any)
├── handover/               # Handover documentation for Codex
└── venv/                   # Local Python virtual environment
```

---

## 2. Request & Execution Flows

### A. General Request Flow
Vercel serverless executes Python handlers inside stateless micro-VMs.
```
User Request
    │
    ▼
Vercel Gateway (vercel.json)
    │
    ▼
api/index.py (Sys path correction, import app)
    │
    ▼
app.py (Flask routing)
    │
    ├─► Session check via @login_required
    │
    └─► Database access via get_db() -> On-demand initialization if not run before
```

### B. Resume Upload & Analysis Flow
```
1. User uploads PDF file via Dashboard UI
    │
    ▼
2. Flask route /analyze-resume (methods=["POST"]) receives the file and job description text
    │
    ▼
3. app.py parses raw text using PdfReader from the pypdf library
    │
    ▼
4. The raw text and job description are compiled into an AI prompt
    │
    ▼
5. call_groq() sends the request to the Groq API (Llama-3.3-70b-versatile)
    │
    ▼
6. AI returns a structured JSON report containing scores and suggestions
    │
    ▼
7. Flask saves the analysis inside the SQLite database (analyses & resumes tables) and returns JSON response to UI
```

---

## 3. Core API Routes Summary

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/` | Home Landing Page | No |
| **GET/POST**| `/login` | Email-based Authentication | No |
| **GET/POST**| `/register`| Account Registration | No |
| **GET** | `/auth/google`| Google OAuth Login Redirect | No |
| **GET** | `/auth/google/callback`| Google OAuth Callback handler | No |
| **GET** | `/dashboard`| Main User Workspace & History | Yes |
| **POST** | `/analyze-resume`| Upload & parse resume, request Groq analysis | Yes |
| **GET** | `/api/analyses/<id>`| Retrieve a saved analysis report | Yes |
| **DELETE**| `/api/analyses/<id>`| Delete a saved analysis report | Yes |
| **POST** | `/api/resumes/export-docx`| Generates a DOCX file from builder state | Yes |
