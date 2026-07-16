# AI Resume Analyzer (MVP)

Flask backend + vanilla HTML/JS frontend. Uploads a resume (PDF/TXT), sends extracted text to Claude, returns structured feedback (score, strengths, weaknesses, ATS issues, suggestions, missing keywords).

## Setup

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Create a `.env` file in this folder with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

3. Run the app:

```bash
python app.py
```

4. Open http://localhost:5000 in your browser.

## How it works

- `app.py` — Flask server. `/api/analyze` accepts a file upload + optional job description, extracts text (pypdf for PDFs), sends a structured prompt to Claude asking for JSON output, parses and returns it.
- `templates/index.html` — single-page UI: upload form, results display, no build step or framework needed.

## Notes / next steps for you

- No database yet — nothing is saved between requests. Add one (e.g. SQLite) if you want history.
- No auth — fine for local/demo use, add auth before any public deployment.
- Resume text is truncated to ~15k chars to keep prompts reasonable; very long resumes get cut off.
- Error handling is minimal — wrap `client.messages.create` calls with retries if you see occasional API hiccups in production.
