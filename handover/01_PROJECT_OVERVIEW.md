# Project Overview: JobSpike (Resume Analyzer)

This document provides a high-level overview of the JobSpike (Resume Analyzer) project, including its core purpose, MVP scope, technology stack, and current roadmap.

---

## 1. Project Purpose
JobSpike is an AI-powered resume analysis, ATS scoring, and resume optimization web application. It aims to help candidates improve their resumes by analyzing them against specific job descriptions, identifying keyword gaps, diagnosing formatting issues, and rewriting weak sections using recruiter-grade AI feedback.

---

## 2. MVP Goals
The current target MVP (Version 1.0) focuses on delivering six core workflows:
1. **Google OAuth & Email Authentication**: Secure registration and session management.
2. **Resume Parser (PDF & DOCX)**: Extracting raw text from uploaded files.
3. **ATS Scoring & Feedback**: Breaking down the resume's competitiveness into priority actionable insights.
4. **AI-Powered Keyword & Formatting Suggestions**: Extracting key terms from the job description and finding overlaps.
5. **AI Resume Rewrite / Polish**: Re-wording bullet points and sections to maximize impact.
6. **Download / Export**: Exporting optimized resumes as formatted DOCX or PDF.

---

## 3. Technology Stack & Frameworks

| Layer | Technology | Version / Details |
| :--- | :--- | :--- |
| **Core Backend** | Python / Flask | Flask 3.0+ / Python 3.9+ |
| **Frontend Stack** | HTML / CSS (Vanilla) | Custom modern dark-theme SaaS UI with CSS variables, Inter/Plus Jakarta Sans fonts |
| **AI Providers** | Groq (primary) / OmniRoute | Llama 3.3 70B (via Groq API or OmniRoute local router) |
| **Storage / DB** | SQLite (local) / Turso (cloud fallback) | Standard `sqlite3` library locally, `libsql-client` (fallback, currently disabled) |
| **Deployment** | Vercel (Serverless Functions) | Vercel Python runtime using `api/index.py` WSGI entrypoint |

---

## 4. Current Feature Status

### Completed Features
- **PDF Text Parsing**: Fully integrated using the `pypdf` library.
- **Groq API Client Integration**: Robust client setup inside `app.py` utilizing `groq` to analyze resumes against job descriptions.
- **Standard Routing & Views**: UI templates for login, dashboard, analysis history, and resume generation.
- **On-Demand Table Initialization**: Refactored database connections in `app.py` to lazily construct SQLite tables inside `/tmp/resumeai.db` or Turso on the first database call, preventing import-time crashes.
- **Urllib parse URL encode migration**: Migrated from the deprecated `requests.compat.urlencode` to `urllib.parse.urlencode`.

### Incomplete Features & Roadmap
- **Google OAuth Login**: Backend templates and routes exist but need verification of client credentials.
- **Full DOCX Resume Builder**: Interface elements exist; export functionality needs validation.
- **Persistent Cloud Database (Turso/Postgres)**: Currently configured to fall back to an ephemeral `/tmp/resumeai.db` on Vercel. Needs Turso or Supabase integration.
- **OmniRoute AI Integration**: System is configured to talk directly to Groq. Integration of a local local routing proxy (`http://localhost:20128/v1`) is planned but not complete.
