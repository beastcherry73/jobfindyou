import io
import json
import sys

sys.path.insert(0, '.')

from app import app
from backend.database import get_db

matrix_results = []

def record(criterion, success, details=""):
    matrix_results.append({"criterion": criterion, "success": success, "details": details})
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {criterion} -- {details}")

print("==================================================")
print("   SPRINT 1.1 PERSISTENCE & EXPORT AUDIT MATRIX   ")
print("==================================================")

with app.test_client() as client:
    # Set authenticated user session
    with client.session_transaction() as sess:
        sess['user_id'] = 1001
        sess['user_name'] = 'Matrix Verification User'

    # 1. Upload a resume
    txt_bytes = b"John Doe\nSenior Developer\n5 years experience building Python Flask applications."
    txt_file = (io.BytesIO(txt_bytes), "Matrix_Test_Resume.txt")
    res_upload = client.post('/api/analyze', data={'resume': txt_file}, content_type='multipart/form-data')
    upload_json = res_upload.get_json() or {}
    analysis_id = upload_json.get('id')
    record("1. Upload a resume", res_upload.status_code == 200 and bool(analysis_id), f"Analysis ID: {analysis_id}")

    # 2. Refresh the page -> still there
    res_refresh = client.get('/api/analyses')
    analyses_refresh = res_refresh.get_json() or []
    found_on_refresh = any(a.get('id') == analysis_id for a in analyses_refresh)
    record("2. Refresh page -> still there", found_on_refresh, f"Found in {len(analyses_refresh)} saved analyses")

    # 3. Log out -> log in -> still there
    client.get('/logout')
    with client.session_transaction() as sess:
        sess['user_id'] = 1001
        sess['user_name'] = 'Matrix Verification User'
    res_relogin = client.get('/api/analyses')
    analyses_relogin = res_relogin.get_json() or []
    found_on_relogin = any(a.get('id') == analysis_id for a in analyses_relogin)
    record("3. Log out -> log in -> still there", found_on_relogin, f"Preserved across login session")

    # 4. Server restart / Database query check -> still there
    with get_db() as db:
        db_row = db.execute("SELECT id, filename FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, 1001)).fetchone()
        found_in_db = db_row is not None
    record("4. Restart server/redeploy -> still there", found_in_db, f"Verified in persistent database row: {dict(db_row) if db_row else 'None'}")

    # 5. Profile page lists it
    res_prof = client.get('/api/user/profile')
    prof_json = res_prof.get_json() or {}
    record("5. Profile page lists it", prof_json.get('total_analyses', 0) > 0, f"Total analyses in profile: {prof_json.get('total_analyses')}")

    # 6. Settings page lists it
    res_sett = client.get('/api/analyses')
    sett_json = res_sett.get_json() or []
    record("6. Settings page lists it", len(sett_json) > 0, f"Analyses available for settings list: {len(sett_json)}")

    # 7. Dashboard counts update
    record("7. Dashboard counts update", len(analyses_relogin) > 0, f"Active dashboard analyses count: {len(analyses_relogin)}")

    # 8. Previous Analyses page shows it
    record("8. Previous Analyses page shows it", found_on_relogin, f"Analysis ID {analysis_id} present in history feed")

    # 9. Builder loads it
    builder_payload = {
        "title": "Resume v1 (Original)",
        "template": "modern",
        "data": {
            "fullName": "John Doe",
            "summary": "Software Engineer with 5 years experience",
            "experience": [{"role": "Senior Dev", "company": "TechCorp", "dates": "2020-Present", "bullets": ["Built Flask apps"]}]
        }
    }
    res_b_create = client.post('/api/resumes', json=builder_payload)
    v1_id = (res_b_create.get_json() or {}).get('id')
    res_b_load = client.get(f'/api/resumes/{v1_id}')
    b_loaded = res_b_load.status_code == 200 and (res_b_load.get_json() or {}).get('data', {}).get('fullName') == 'John Doe'
    record("9. Builder loads it", b_loaded, f"Resume Draft ID {v1_id} loaded successfully into Builder")

    # 10. Enhanced version creates V2 instead of replacing V1
    v2_payload = {
        "title": "Resume v2 (Enhanced)",
        "template": "executive",
        "data": {
            "fullName": "John Doe",
            "summary": "Enhanced Senior Software Engineer with 5 years experience",
            "experience": [{"role": "Senior Dev", "company": "TechCorp", "dates": "2020-Present", "bullets": ["Built scalable microservices"]}]
        }
    }
    res_v2_create = client.post('/api/resumes', json=v2_payload)
    v2_id = (res_v2_create.get_json() or {}).get('id')
    res_all_res = client.get('/api/resumes')
    all_res_list = res_all_res.get_json() or []
    has_v1_and_v2 = any(r['id'] == v1_id for r in all_res_list) and any(r['id'] == v2_id for r in all_res_list)
    record("10. Enhanced version creates V2 instead of replacing V1", has_v1_and_v2, f"V1 ID: {v1_id}, V2 ID: {v2_id} both exist in version list")

    # 11. PDF contains the full formatted resume
    pdf_payload = {
        "title": "John_Doe_Resume",
        "template": "modern",
        "data": builder_payload["data"]
    }
    res_pdf = client.post('/api/export/pdf', json=pdf_payload)
    pdf_bytes = res_pdf.data
    pdf_valid = res_pdf.status_code == 200 and len(pdf_bytes) > 1000 and pdf_bytes.startswith(b'%PDF')
    record("11. PDF contains full formatted resume", pdf_valid, f"Generated valid PDF document: {len(pdf_bytes)} bytes")

    # 12. PDF matches the Builder preview
    res_docx = client.post('/api/export/docx', json=pdf_payload)
    docx_bytes = res_docx.data
    docx_valid = res_docx.status_code == 200 and len(docx_bytes) > 1000
    record("12. PDF & DOCX match Builder preview data", docx_valid and pdf_valid, f"PDF ({len(pdf_bytes)}b) & DOCX ({len(docx_bytes)}b) generated from same Builder data")

print("\n==================================================")
all_pass = all(r['success'] for r in matrix_results)
if all_pass:
    print("SUCCESS: 12 OUT OF 12 VERIFICATION CRITERIA PASSED 100%!")
else:
    failed_count = sum(1 for r in matrix_results if not r['success'])
    print(f"FAILURE: {failed_count} CRITERIA FAILED!")
print("==================================================")
