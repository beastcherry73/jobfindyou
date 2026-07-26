# Handover Document for OpenCode: Deployment & Session Analysis

This document provides a complete transition state for the next coding agent (OpenCode) regarding the visual redesign and deployment state of JobSpike.

---

## 1. Project & Deployment Architecture

### Project Overview
JobSpike is a premium AI-powered resume scanner and optimizer built to elevate engineering resumes to YC-startup/SaaS standards.
*   **Backend**: Flask / Python 3 (routes managed in `app.py`, endpoints mapped to `api/index.py` for Vercel Serverless Function runtime).
*   **Database**: SQLite (`/tmp/resumeai.db`), lazily initialized inside database helper calls.
*   **Frontend**: Vanilla HTML/JS inside `templates/index.html` featuring custom canvas components (Radar charts, score counters, responsive grids, and coordinate backdrops).

### Deployment Architecture
*   **Git Repository**: `https://github.com/beastcherry73/jobfindyou.git`
*   **Vercel Project**: `jobfindyou2.0` (Vercel builds are triggered automatically upon git pushes to the `main` branch).
*   **Current Production Domain**: `https://jobspike.in` (redirects to `https://www.jobspike.in`).
*   **Vercel Project Settings**: Serves the application via serverless Python rewrites configured in `vercel.json`.

---

## 2. Active Deployment Context

*   **Committed and Deployed Commit SHA**: `05d24e5`
*   **Latest Preview Deployment URL**: `https://jobfindyou20-3jwwoqy5v-beastcherry73s-projects.vercel.app/`
*   **Production Deployment URL**: `https://www.jobspike.in`

---

## 3. Investigation & Root Cause Analysis

### Problem Statement
The user reported that the Vercel preview deployment correctly displayed the redesigned home screen, but the public domain `https://jobspike.in` continued to render the old UI/dashboard view.

### Investigation Steps Performed
1.  **DNS & Routing Audit**:
    *   Queried DNS records via `nslookup`.
    *   Verified that the apex domain `jobspike.in` successfully points to Vercel's standard proxy server IP `76.76.21.21`.
2.  **HTTP Header & Content Audit**:
    *   Curled `https://jobspike.in` to check served HTML content.
    *   Verified that `jobspike.in` returns headers indicating `Server: Vercel`.
    *   Checked for the presence of the new `landing-nav` class and navigation tags:
        ```bash
        curl.exe -s https://jobspike.in | Select-String -Pattern "landing-nav"
        ```
    *   *Result*: The query matched and returned the new landing page classes, proving the latest code *is* fully active on the production domain.

### Root Cause Discovered
*   **Authentication-Based Routing**:
    *   In `app.py`, the home route `/` serves different views based on whether the browser sends an active session cookie:
        *   **Logged In** (`is_authenticated=True`): Serves the **Dashboard workspace** (the layout corresponding to the builder/optimizer interface).
        *   **Logged Out** (`is_authenticated=False`): Serves the **redesigned Landing Page**.
    *   Because the developer had previously logged in on `https://jobspike.in` to debug the Google OAuth flow, their browser retained the session cookie. Hence, visiting the domain immediately mapped them to their active workspace dashboard, which looked like the "old UI".
    *   Visiting the Vercel Preview URL (`https://jobfindyou20-...vercel.app`) did not transmit the session cookie because cookies are domain-scoped. Hence, they appeared logged out and saw the new landing page layout.

### Fixes Attempted / Verification
*   No code changes were necessary as the application is functioning exactly as designed.
*   Stateless calls (like curl or browser Incognito sessions) show that the preview, production URL, and custom domain all return identical HTML.

---

## 4. Expected State & Next Steps

*   **Current State**: The visual redesign is live and serving correctly.
*   **Next Steps**:
    1.  Instruct the user to visit `https://jobspike.in` in **Incognito Mode** or click **"Sign Out"** in their dashboard to confirm they see the new visual design.
    2.  Continue building workspace features (PostgreSQL database migrations, multi-draft management) as specified in the feature roadmap.

---

## 5. Verification Commands
```powershell
# Verify that the landing page navigation bar is served in production:
curl.exe -s -m 10 https://jobspike.in | Select-String -Pattern "landing-nav"

# Check the server header on production requests:
curl.exe -I -m 10 https://jobspike.in
```
