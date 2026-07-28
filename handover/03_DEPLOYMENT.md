# Deployment Reference: Vercel & GitHub

This document describes the hosting environment, the configuration settings in `vercel.json`, the deployment process, and the application startup sequence.

---

## 1. Hosting Environment
- **Platform**: Vercel (Serverless Functions)
- **Repository**: `https://github.com/beastcherry73/jobfindyou.git`
- **Main Branch**: `main`
- **Domain**: `https://www.jobspike.in`

---

## 2. Configuration Settings (`vercel.json`)
The application routes all incoming traffic to `api/index.py`, which is the entrypoint. It also instructs Vercel to bundle the HTML/CSS templates so Flask can render them from the serverless sandbox.

```json
{
  "version": 2,
  "functions": {
    "api/index.py": {
      "includeFiles": [
        "templates/**",
        "static/**"
      ]
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

## 3. Deployment & Build Pipeline
1. **Trigger**: When a commit is pushed to the `main` branch on GitHub, Vercel automatically hooks into the repository to run a new deployment build.
2. **Pip Install**: Vercel reads `requirements.txt` to install all dependencies.
   - **Important**: Native C-extension packages (such as `libsql-client`) must be avoided or kept optional in requirements because the AWS Lambda environment will fail to build or run them due to missing linking libraries.
3. **Packaging**: Vercel compiles `/api/index.py` and copies any folders specified in `includeFiles` (`templates` and `static`) into the deployment sandbox.

---

## 4. Entrypoint and Startup Sequence
When Vercel initializes a serverless container to handle an HTTP request, the following sequence occurs:

1. **Python Import of Entrypoint**: Vercel imports the `api/index.py` module.
2. **System Path Insertion**:
   - `api/index.py` calculates the parent root directory of the workspace and inserts it into `sys.path`.
3. **Flask Application Import**:
   - `api/index.py` executes `from app import app`.
4. **App Level Setup**:
   - `app.py` is executed.
   - Core configurations are loaded from `os.environ` (e.g. `SECRET_KEY`, `GROQ_API_KEY`).
   - The database configuration is set to `/tmp/resumeai.db` or Turso.
   - **Crucial**: No database queries, connections, or initializations are executed at the module import level. The application waits until a request is received.
5. **WSGI Handler Binding**:
   - `api/index.py` binds the Flask `app` object to `handler` and `application` variables, which Vercel's wrapper exposes to the web gateway.
