# Root Cause Analysis: Lovable Landing Page Integration

## Summary

The Lovable landing page integration into the existing JobSpike Flask application
failed due to **three independent defects**, each breaking a different part of the
guest-to-dashboard user journey.

---

## Root Cause #1 — Dashboard CSS unconditionally polluting the Lovable landing page

### What broke

The Lovable landing page's Tailwind-based layout was overridden by the dashboard's
generic CSS selectors (`.sidebar`, `.nav-link`, `.btn-primary`, `.card`, `.stat-card`,
`.table`, etc.), causing:

- Hero section overflowing
- Navbar styling broken
- Sections overlapping
- Layout rendering differently from the Lovable preview

### Why it broke

**File:** `templates/index.html`
**Lines:** 10–295 (dashboard `<style>` block)

The dashboard CSS was placed **outside** any authentication block. Every page
visitor — including unauthenticated users viewing the landing page — received
~200 lines of dashboard stylesheets. These generic class names collided directly
with Lovable's Tailwind utility classes (`.bg-canvas`, `.text-ink`, `.grain`,
`.font-serif`, etc.).

### Fix

Wrapped the dashboard `<style>` block in `{% if is_authenticated %}` ... `{% endif %}`.
Unauthenticated users now only receive the Lovable CSS (Tailwind + dark theme).

### Commit

`2545eeb`

---

## Root Cause #2 — React SPA overrides native onclick handlers on the landing page

### What broke

Every clickable element on the landing page became non-functional:

- "Upload Resume" → does nothing
- "Sign In" → does nothing
- Navigation links → do nothing
- Pricing CTAs → do nothing
- Footer links → do nothing

The entire landing page felt like a static HTML page.

### Why it broke

**File:** `templates/index.html`
**Line (before fix):** `<script type="module" async="" src="/static/assets/index-B4fdfMeO.js"></script>`
**File on disk:** `static/assets/index-B4fdfMeO.js` (345 KB bundled React SPA)

The Lovable build output is a full React SPA with TanStack Router. The Lovable
landing page HTML is React Server-Side Rendered (SSR) output. When the React
app module script loads in the browser, it **hydrates** the page — React walks
the existing DOM and attaches its own event delegation system.

The custom Flask handlers (`triggerLandingUpload()`, `openAuthModal()`) are
defined in a separate `<script>` block as native `onclick` attributes on the
HTML elements. However, React's hydration process:

1. **Replaces** DOM elements that don't match its virtual DOM
2. **Overrides** native `onclick` handlers with React's synthetic event system
3. Takes over the page with its own component lifecycle

Since the React SPA's components have their own `onClick` handlers that don't
call `openAuthModal()` or `triggerLandingUpload()`, all the `onclick` attributes
became inert. The React app was loaded — and running — but its event handlers
did nothing useful for the Flask integration.

The two JavaScript execution contexts (React and vanilla Flask) conflicted
directly, and React won because it controls the entire DOM after hydration.

### Fix

Removed the `<script type="module" async="" src="/static/assets/index-B4fdfMeO.js">`
tag from the minified Lovable HTML. The server-rendered Lovable HTML already
contains all content and styling. The custom `<script>` block (defining
`triggerLandingUpload`, `openAuthModal`, `closeAuthModal`, and scroll reveal)
handles all interactive behavior correctly without React interference.

The TanStack Router SSR data script (`$tsr-stream-barrier`) remains in the HTML
but is inert — it configures router state that is never used, causing no issues.

### Commit

`3f31bdc`

---

## Root Cause #3 — Guest handshake did not auto-trigger analysis after login

### What broke

A guest user could upload a resume on the landing page, authenticate, and see
the file transferred to the dashboard — but the ATS analysis never ran. The
user had to manually click "Run ATS Audit" to begin analysis.

### Why it broke

**File:** `templates/index.html`
**Lines:** 943–983 (guest handshake code)

The guest handshake correctly:
1. Reads the pending file from `sessionStorage`
2. Converts base64 back to a `File` object
3. Sets it on the dashboard's `resumeFile` input
4. Dispatches a change event

But it never called `analyzeBtn.click()` to trigger the analysis. The user
flow ended at "file populated in input" instead of "analysis running."

### Fix

Added auto-trigger of analysis after the file transfer. After a 150ms delay
(to ensure UI is ready), the handshake switches to the analyze tab and clicks
the "Run ATS Audit" button:

```javascript
setTimeout(() => {
    if (typeof switchTab === 'function') switchTab('analyze');
    const btn = document.getElementById('analyzeBtn');
    if (btn) btn.click();
}, 150);
```

### Commit

`3f31bdc`

---

## Files Modified

| File | Change | Commits |
|------|--------|---------|
| `templates/index.html` | Wrapped dashboard CSS in `{% if is_authenticated %}` | `2545eeb` |
| `templates/index.html` | Wrapped dashboard JS in `{% if is_authenticated %}` | `2545eeb` |
| `templates/index.html` | Removed React SPA module script tag | `3f31bdc` |
| `templates/index.html` | Guest handshake now auto-triggers analysis | `3f31bdc` |

## Only file touched: one file, two commits
