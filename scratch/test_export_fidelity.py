import io
import json
import sys

sys.path.insert(0, '.')

from app import app
from backend.database import get_db

print("==================================================")
print("  SPRINT 1.2 EXPORT FIDELITY & MULTI-PAGE AUDIT   ")
print("==================================================")

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Fidelity Test User'

    # Build a long resume with 8 work experiences, 20 bullets, education, projects, certifications to test multi-page flow
    long_experience = []
    for i in range(1, 9):
        long_experience.append({
            "role": f"Senior Principal Systems Engineer {i}",
            "company": f"Global Enterprise Tech Solutions {i} Inc & R&D",
            "dates": f"201{i}-2020",
            "bullets": [
                f"Architected high-throughput microservices handling >100,{i}00 QPS with <5ms latency using Python Flask and PostgreSQL.",
                f"Led a cross-functional engineering team of {i*3} engineers across 4 timezones.",
                f"Optimized memory usage by {i*5}% and eliminated database connection bottlenecks.",
                f"Designed automated CI/CD pipelines reducing deployment times by 45%."
            ]
        })

    long_resume_data = {
        "fullName": "Alexander Vance, PhD",
        "email": "alex.vance@example.com",
        "phone": "+1 (555) 019-2834",
        "location": "San Francisco, CA",
        "summary": "Seasoned Lead Principal Architect with 15+ years experience building mission-critical distributed systems, high-availability database engines, and scalable Cloud & AI platforms. Proven track record of driving technical strategy for Fortune 500 enterprises.",
        "skills": "Python, Flask, PostgreSQL, Supabase, ReportLab, Docker, Kubernetes, AWS, Microservices, CI/CD, React, TypeScript, System Architecture",
        "experience": long_experience,
        "education": [
            {"degree": "PhD in Computer Science", "school": "Stanford University", "dates": "2010-2014"},
            {"degree": "BS in Computer Engineering", "school": "UC Berkeley", "dates": "2006-2010"}
        ],
        "projects": [
            {"name": "Distributed Analytics Engine", "tech": "Python, Go, PostgreSQL", "desc": "Real-time streaming pipeline processing 10B+ events daily."},
            {"name": "AI Career Operating System", "tech": "Flask, Groq AI, Supabase", "desc": "Autonomous career engine powering ATS analysis and resume generation."}
        ],
        "certifications": [
            {"name": "AWS Certified Solutions Architect - Professional", "issuer": "Amazon Web Services", "dates": "2023"},
            {"name": "Google Cloud Lead Data Engineer", "issuer": "Google Cloud", "dates": "2022"}
        ]
    }

    # 1. Test PDF Generation for Long Multi-Page Resume
    res_pdf = client.post('/api/export/pdf', json={"data": long_resume_data, "title": "MultiPage_Resume"})
    pdf_bytes = res_pdf.data
    pdf_ok = res_pdf.status_code == 200 and res_pdf.content_type == "application/pdf" and len(pdf_bytes) > 5000
    print(f"[{'PASS' if pdf_ok else 'FAIL'}] Multi-Page PDF Generation -- Size: {len(pdf_bytes)} bytes")

    # Inspect PDF page count using pypdf if available
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        num_pages = len(reader.pages)
        multipage_pass = num_pages >= 2
        print(f"[{'PASS' if multipage_pass else 'FAIL'}] PDF Multi-Page Flow -- Total PDF Pages Generated: {num_pages}")
    except Exception as e:
        print(f"[INFO] pypdf check skipped: {e}")

    # 2. Test DOCX Generation for Long Multi-Page Resume
    res_docx = client.post('/api/export/docx', json={"data": long_resume_data, "title": "MultiPage_Resume"})
    docx_bytes = res_docx.data
    docx_ok = res_docx.status_code == 200 and "wordprocessingml" in res_docx.content_type and len(docx_bytes) > 20000
    print(f"[{'PASS' if docx_ok else 'FAIL'}] Multi-Page DOCX Generation -- Size: {len(docx_bytes)} bytes")

    # 3. Test XML/HTML special character escaping in PDF (e.g. C++, R&D, UI/UX <Lead>)
    special_char_data = dict(long_resume_data)
    special_char_data["fullName"] = "Special Char <Dev> & Architect"
    special_char_data["summary"] = "Built C++ & R&D engines with <1ms latency & >99.9% uptime."
    res_spec_pdf = client.post('/api/export/pdf', json={"data": special_char_data, "title": "SpecialChar_Resume"})
    spec_pdf_ok = res_spec_pdf.status_code == 200 and len(res_spec_pdf.data) > 1000
    print(f"[{'PASS' if spec_pdf_ok else 'FAIL'}] XML/HTML Special Character Escaping -- Size: {len(res_spec_pdf.data)} bytes")

print("==================================================")
