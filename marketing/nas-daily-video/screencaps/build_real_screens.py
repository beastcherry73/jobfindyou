"""Builds real-data screen captures from the live jobspike.in DOM dump.

The SPA keeps every section mounted in the DOM simultaneously and just
toggles `display`, so a single .ws-main dump (captured from the logged-in
Browser pane, screencaps/dom_upload_main.html) contains ALL of: the ATS
report (94%), the Improve Resume rewrite comparison (74% -> 76%), and the
For You job matches (85/78/75/70%) -- all real production data, real
companies, no fabricated numbers.

This script slices out one target <section> at a time, re-wraps it with
the sidebar (real user name swapped for a placeholder -- this is going into
a public ad) and the real production stylesheet, and renders each to a PNG
via headless Chrome for the video pipeline.
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with open(os.path.join(HERE, "dom_upload_main.html"), encoding="utf-8") as f:
    MAIN_HTML = f.read()

SIDEBAR_HTML = r'''<aside class="ws-sidebar" id="sidebar">
      <div class="ws-sidebar-header">
        <a href="/" class="ws-sidebar-brand">
          <span class="ws-sidebar-mark brand">
            <img src="https://www.jobspike.in/static/img/jobspike-icon.svg" alt="" width="17" height="17">
          </span>
          <span class="ws-sidebar-name">
            <img class="ws-brand-light" src="https://www.jobspike.in/static/img/jobspike-wordmark.svg" alt="JobSpike" height="17">
            <img class="ws-brand-dark" src="https://www.jobspike.in/static/img/jobspike-wordmark-on-dark.svg" alt="" aria-hidden="true" height="17">
          </span>
        </a>
      </div>
      <nav class="ws-sidebar-nav">
        <a class="ws-nav-item" data-section="dashboard"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"></rect><rect x="14" y="3" width="7" height="5" rx="1.5"></rect><rect x="14" y="12" width="7" height="9" rx="1.5"></rect><rect x="3" y="16" width="7" height="5" rx="1.5"></rect></svg></span><span class="ws-nav-label">Dashboard</span></a>
        <div class="ws-nav-section-label" style="margin-top:8px;">Jobs</div>
        <a class="ws-nav-item {browse_active}" data-section="jobsearch"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg></span><span class="ws-nav-label">Browse</span></a>
        <a class="ws-nav-item {foryou_active}" data-section="foryou"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.4 5.4 5.6.6-4.2 3.9 1.2 5.6L12 15.8 6.9 18.5l1.2-5.6L4 9l5.6-.6z"></path></svg></span><span class="ws-nav-label">For You</span></a>
        <a class="ws-nav-item" data-section="pipeline"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="5" height="16" rx="1.4"></rect><rect x="10" y="4" width="5" height="11" rx="1.4"></rect><rect x="17" y="4" width="4" height="7" rx="1.4"></rect></svg></span><span class="ws-nav-label">Pipeline</span></a>
        <div class="ws-nav-section-label" style="margin-top:8px;">Resume Analysis</div>
        <a class="ws-nav-item {upload_active}" data-section="analysis-upload"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg></span><span class="ws-nav-label">Upload Resume</span></a>
        <a class="ws-nav-item" data-section="history"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"></path></svg></span><span class="ws-nav-label">Previous Analyses</span></a>
        <div class="ws-nav-section-label" style="margin-top:8px;">Improve Resume</div>
        <a class="ws-nav-item {improve_active}" data-section="improve"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17 9 11l4 4 8-8"></path><path d="M17 7h4v4"></path></svg></span><span class="ws-nav-label">Improve Resume</span></a>
        <div class="ws-nav-section-label" style="margin-top:8px;">Resume Builder</div>
        <a class="ws-nav-item" data-section="builder"><span class="ws-nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg></span><span class="ws-nav-label">Build</span></a>
      </nav>
      <div id="persistentHealthBadge" style="margin: 12px 14px; padding: 12px 14px; background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.25); border-radius: 12px; display: flex; align-items: center; justify-content: space-between;">
        <div>
          <div style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ws-text-tertiary);">Resume Health</div>
          <div style="font-size: 1.1rem; font-weight: 800; color: var(--ws-primary);">94 <span style="font-size: 0.7rem; font-weight: 700; color: #16A34A; background: rgba(34,197,94,0.15); padding: 2px 6px; border-radius: 4px; vertical-align: middle;">Excellent</span></div>
        </div>
        <div style="font-size: 0.75rem; font-weight: 700; color: var(--ws-primary);">Improve &rarr;</div>
      </div>
      <div class="ws-sidebar-footer">
        <div class="ws-sidebar-user">
          <div class="ws-sidebar-avatar">A</div>
          <div class="ws-sidebar-user-info">
            <div class="ws-sidebar-user-name">Alex Morgan</div>
            <div class="ws-sidebar-user-email">Free plan</div>
          </div>
        </div>
      </div>
    </aside>'''

PAGE_TEMPLATE = """<!DOCTYPE html><html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://www.jobspike.in/static/css/workspace.css">
<style>html,body{{margin:0;padding:0;}}</style>
</head><body>
<div class="ws-layout">
{sidebar}
<div class="ws-main">
<header class="ws-topbar"><div class="ws-topbar-left"><div class="ws-breadcrumb"><span class="ws-breadcrumb-current">{title}</span></div></div>
<div class="ws-topbar-right"><div class="ws-user-menu"><div class="ws-user-trigger"><div class="ws-user-avatar">A</div></div></div></div></header>
<main class="ws-content">
{section}
</main>
</div>
</div>
</body></html>"""


def extract_section(section_id):
    pattern = rf'<section id="{re.escape(section_id)}"[^>]*>'
    m = re.search(pattern, MAIN_HTML)
    if not m:
        raise RuntimeError(f"section {section_id} not found")
    start = m.start()
    # find the matching closing </section> by depth-counting nested <section> tags
    depth = 0
    pos = start
    open_re = re.compile(r"<section\b")
    close_re = re.compile(r"</section>")
    while True:
        nxt_open = open_re.search(MAIN_HTML, pos + 1)
        nxt_close = close_re.search(MAIN_HTML, pos + 1)
        if nxt_close is None:
            raise RuntimeError("unbalanced sections")
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            pos = nxt_open.start()
        else:
            if depth == 0:
                end = nxt_close.end()
                break
            depth -= 1
            pos = nxt_close.start()
    frag = MAIN_HTML[start:end]
    # force visible regardless of the live page's current display:none state
    frag = re.sub(r'(<section id="' + re.escape(section_id) + r'"[^>]*style=")[^"]*"',
                  r'\1display:block;"', frag, count=1)
    return frag


SCREENS = [
    ("upload", "section-analysis-upload", "Upload Resume", "upload_active"),
    ("score", "section-report", "ATS Report", None),
    ("rewrite", "section-improve", "Improve Resume", "improve_active"),
    ("match", "section-foryou", "For You", "foryou_active"),
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])


for name, section_id, title, active_key in SCREENS:
    frag = extract_section(section_id)
    sidebar = SIDEBAR_HTML.format(
        browse_active="active" if active_key == "browse_active" else "",
        foryou_active="active" if active_key == "foryou_active" else "",
        upload_active="active" if active_key == "upload_active" else "",
        improve_active="active" if active_key == "improve_active" else "",
    )
    page = PAGE_TEMPLATE.format(sidebar=sidebar, title=title, section=frag)
    html_path = os.path.join(HERE, f"real_{name}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    png_path = os.path.join(HERE, f"real_{name}.png")
    profile = os.path.join(HERE, f"chrome_profile_{name}")
    run(["cmd", "/c", "rmdir", "/s", "/q", profile]) if os.path.exists(profile) else None
    run([
        CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=1280,900",
        "--virtual-time-budget=4000", f"--user-data-dir={profile}",
        f"--screenshot={png_path}",
        f"file:///{html_path.replace(os.sep, '/')}",
    ])
    print("rendered", png_path)
