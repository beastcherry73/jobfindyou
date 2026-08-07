import io
import json
import os
import sys

sys.path.insert(0, '.')

from app import app
from backend.database import get_db

results = []

def record(test_name, success, details=""):
    results.append({"test": test_name, "success": success, "details": details})
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {test_name} - {details}")

print("==================================================")
print("     JOB SPIKE COMPLETE PRODUCTION ROUTE AUDIT     ")
print("==================================================")

with app.test_client() as client:
    # 1. Unauthenticated Route Tests
    unauth_routes = [
        ('/', 200),
        ('/auth/login', 200),
        ('/auth/register', 200),
        ('/workspace', 200),
        ('/dashboard', 200),
        ('/analysis', 200),
        ('/builder', 200),
        ('/improve', 200),
        ('/tracker', 200),
        ('/profile', 200),
        ('/settings', 200),
        ('/billing', 200),
    ]

    for route, expected_code in unauth_routes:
        res = client.get(route)
        record(f"GET {route} (Unauth)", res.status_code == expected_code, f"Status: {res.status_code}")

    # 2. Guest Resume Upload
    txt_bytes = b"John Doe\nSoftware Engineer\n5 years experience building Python Flask applications."
    txt_file = (io.BytesIO(txt_bytes), "Guest_Test_Resume.txt")
    res_guest_upload = client.post('/api/analyze', data={'resume': txt_file}, content_type='multipart/form-data')
    guest_upload_ok = res_guest_upload.status_code == 200 and 'overall_score' in (res_guest_upload.get_json() or {})
    record("Guest POST /api/analyze", guest_upload_ok, f"Status: {res_guest_upload.status_code}")

    # 3. Authenticated Session Setup
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user_name'] = 'Audit Tester'

    # 4. Authenticated Resume Upload
    txt_file_auth = (io.BytesIO(txt_bytes), "Auth_Test_Resume.txt")
    res_auth_upload = client.post('/api/analyze', data={'resume': txt_file_auth}, content_type='multipart/form-data')
    auth_upload_data = res_auth_upload.get_json() or {}
    auth_upload_ok = res_auth_upload.status_code == 200 and 'overall_score' in auth_upload_data
    record("Auth POST /api/analyze", auth_upload_ok, f"Status: {res_auth_upload.status_code}")

    # 5. GET /api/analyses
    res_analyses = client.get('/api/analyses')
    analyses_list = res_analyses.get_json() or []
    analyses_ok = res_analyses.status_code == 200 and isinstance(analyses_list, list)
    record("GET /api/analyses", analyses_ok, f"Returned {len(analyses_list)} items")

    # 6. GET /api/analyses/<id>
    if analyses_list:
        latest_id = analyses_list[0]['id']
        res_analysis_detail = client.get(f'/api/analyses/{latest_id}')
        record(f"GET /api/analyses/{latest_id}", res_analysis_detail.status_code == 200, f"Status: {res_analysis_detail.status_code}")
    else:
        record("GET /api/analyses/<id>", False, "No analyses available to test")

    # 7. GET /api/resumes
    res_resumes = client.get('/api/resumes')
    resumes_list = res_resumes.get_json() or []
    resumes_ok = res_resumes.status_code == 200 and isinstance(resumes_list, list)
    record("GET /api/resumes", resumes_ok, f"Returned {len(resumes_list)} items")

    # 8. POST /api/resumes (Create draft)
    draft_payload = {
        "title": "Resume v2 (Audit Test)",
        "template": "modern",
        "data": {"fullName": "Audit User", "summary": "Test summary"}
    }
    res_create_resume = client.post('/api/resumes', json=draft_payload)
    create_resume_data = res_create_resume.get_json() or {}
    create_resume_ok = res_create_resume.status_code == 200 and 'id' in create_resume_data
    record("POST /api/resumes (Create)", create_resume_ok, f"Status: {res_create_resume.status_code}, ID: {create_resume_data.get('id')}")

    # 9. POST /api/generate/improve-with-diff (Text Payload)
    text_enhance_payload = {
        "resume_text": "Software Engineer with 5 years experience in Python and Flask.",
        "mode": "safe",
        "instructions": "Senior Backend Developer at Stripe"
    }
    res_enhance_text = client.post('/api/generate/improve-with-diff', json=text_enhance_payload)
    enhance_text_data = res_enhance_text.get_json() or {}
    enhance_text_ok = res_enhance_text.status_code == 200 and 'resume' in enhance_text_data
    record("POST /api/generate/improve-with-diff (Text)", enhance_text_ok, f"Status: {res_enhance_text.status_code}")

    # 10. POST /api/generate/improve-with-diff (File Stream Payload)
    txt_file_enhance = (io.BytesIO(txt_bytes), "Enhance_File.txt")
    res_enhance_file = client.post('/api/generate/improve-with-diff', data={'resume': txt_file_enhance, 'mode': 'safe'}, content_type='multipart/form-data')
    enhance_file_data = res_enhance_file.get_json() or {}
    enhance_file_ok = res_enhance_file.status_code == 200 and 'resume' in enhance_file_data
    record("POST /api/generate/improve-with-diff (File)", enhance_file_ok, f"Status: {res_enhance_file.status_code}")

    # 11. POST /api/export/docx
    res_docx = client.post('/api/export/docx', json={"text": "# John Doe\n## Summary\nAudit Test Resume Content", "title": "Audit_Export"})
    record("POST /api/export/docx", res_docx.status_code == 200 and "wordprocessingml" in res_docx.content_type, f"Status: {res_docx.status_code}")

    # 12. POST /api/export/pdf
    res_pdf = client.post('/api/export/pdf', json={"text": "# John Doe\n## Summary\nAudit Test Resume Content", "title": "Audit_Export"})
    record("POST /api/export/pdf", res_pdf.status_code == 200 and res_pdf.content_type == "application/pdf", f"Status: {res_pdf.status_code}")

    # 13. GET /api/user/profile
    res_profile = client.get('/api/user/profile')
    record("GET /api/user/profile", res_profile.status_code == 200 and 'user' in (res_profile.get_json() or {}), f"Status: {res_profile.status_code}")

print("\n==================================================")
fails = [r for r in results if not r['success']]
if not fails:
    print("SUCCESS: 100% OF AUDIT TESTS PASSED WITH ZERO FAILURES!")
else:
    print(f"WARNING: {len(fails)} AUDIT TESTS FAILED!")
print("==================================================")
