# Codebase File Index

This index lists the purpose, responsibility, imports, and related files for the major components of the repository.

---

## 1. `app.py`
- **Location**: `c:\Users\venut\OneDrive\Desktop\Resume analyzer\app.py`
- **Purpose**: Main Flask backend application code.
- **Responsibilities**:
  - Initializes the Flask application context.
  - Registers all user authentication, dashboard, upload, and optimization routes.
  - Handles database connection pooling, table definitions, and migrations.
  - Parses PDF documents using `pypdf`.
  - Coordinates Groq LLM API requests and normalizes responses.
- **Dependencies**: `flask`, `pypdf`, `groq`, `sqlite3`, `dotenv`
- **Related Files**:
  - [api/index.py](file:///c:/Users/venut/OneDrive/Desktop/Resume%20analyzer/api/index.py) (imports `app`)
  - [vercel.json](file:///c:/Users/venut/OneDrive/Desktop/Resume%20analyzer/vercel.json) (routes endpoints to index.py)
  - [templates/](file:///c:/Users/venut/OneDrive/Desktop/Resume%20analyzer/templates/) (rendered by app.py routing)

---

## 2. `api/index.py`
- **Location**: `c:\Users\venut\OneDrive\Desktop\Resume analyzer\api\index.py`
- **Purpose**: Vercel Serverless Function entrypoint.
- **Responsibilities**:
  - Modifies `sys.path` to ensure the project root is discoverable during serverless imports.
  - Imports the Flask application object `app` from `app.py`.
  - Binds the app to `handler` and `application` as required by the WSGI wrapper on Vercel.
- **Dependencies**: `os`, `sys`, `app`
- **Related Files**:
  - [app.py](file:///c:/Users/venut/OneDrive/Desktop/Resume%20analyzer/app.py)

---

## 3. `vercel.json`
- **Location**: `c:\Users\venut\OneDrive\Desktop\Resume analyzer\vercel.json`
- **Purpose**: Project deployment mapping.
- **Responsibilities**:
  - Defines the Vercel version, functions, routing, and file bundles.
- **Related Files**:
  - [api/index.py](file:///c:/Users/venut/OneDrive/Desktop/Resume%20analyzer/api/index.py)
