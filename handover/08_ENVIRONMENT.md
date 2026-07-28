# Environment Variables Documentation

This document describes all environment variables used by the application for authentication, database connection, session signature, and AI requests.

---

## 1. Required Variables

| Name | Description | Placement |
| :--- | :--- | :--- |
| **`SECRET_KEY`** | Secret key used by Flask to cryptographically sign user sessions. Crucial for user logins. | Vercel Env Settings & local `.env` |
| **`GROQ_API_KEY`**| API Key for Groq. Used to access the Llama 3.3 70B model to perform resume optimization. | Vercel Env Settings & local `.env` |

---

## 2. Optional / Fallback Variables

| Name | Description | Placement |
| :--- | :--- | :--- |
| **`GOOGLE_CLIENT_ID`**| Client ID for Google OAuth login verification. | Vercel Env Settings & local `.env` |
| **`GOOGLE_CLIENT_SECRET`**| Client Secret for Google OAuth authentication callback. | Vercel Env Settings & local `.env` |
| **`GOOGLE_REDIRECT_URI`**| OAuth callback path. Defaults to `http://localhost:5000/auth/google/callback` locally. Must be `https://www.jobspike.in/auth/google/callback` on production. | Vercel Env Settings & local `.env` |

---

## 3. Database Sync Variables (Optional)

| Name | Description | Placement |
| :--- | :--- | :--- |
| **`TURSO_DATABASE_URL`**| The connection URL to a hosted Turso serverless SQLite database. If defined, the application attempts to use Turso. | Vercel Env Settings |
| **`TURSO_AUTH_TOKEN`**| Bearer authentication token for Turso cloud database connection. | Vercel Env Settings |

---

## 4. Unused or Deprecated Variables
- **`DATABASE_URL`**: Currently unused since the application is structured around SQLite (`app.config["DATABASE"]`) and Turso configuration parameters rather than a generic Postgres connection string.
