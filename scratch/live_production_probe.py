import os
import sys
import json
import time
import requests
from urllib.parse import urlparse

BASE_URL = "https://www.jobspike.in"

print("==========================================================")
print("     LIVE PRODUCTION DIAGNOSTIC PROBE (www.jobspike.in)    ")
print("==========================================================")

session = requests.Session()
session.headers.update({
    "User-Agent": "JobSpike-Production-Diagnostic-Probe/1.0"
})

# Step 1: Probe health / base homepage
print("\n--- 1. Testing Homepage / Production Endpoint ---")
try:
    res = session.get(BASE_URL, timeout=10)
    print(f"[HTTP {res.status_code}] GET {BASE_URL}")
    print(f"Headers: {dict(res.headers)}")
except Exception as e:
    print(f"FAILED to reach {BASE_URL}: {e}")
    sys.exit(1)

# Step 2: Register a throwaway test user account
timestamp = int(time.time())
test_email = f"probe_user_{timestamp}@jobspike-test.com"
test_pass = "TestPass123!@#"
test_name = f"Probe User {timestamp}"

print(f"\n--- 2. Creating Throwaway Account ({test_email}) ---")
reg_res = session.post(
    f"{BASE_URL}/register",
    data={"name": test_name, "email": test_email, "password": test_pass},
    allow_redirects=True,
    timeout=10
)
print(f"[HTTP {reg_res.status_code}] POST /register -> Final URL: {reg_res.url}")
print(f"Cookies after register: {session.cookies.get_dict()}")

# Check profile to verify session user_id
prof_res = session.get(f"{BASE_URL}/api/user/profile", timeout=10)
print(f"[HTTP {prof_res.status_code}] GET /api/user/profile")
print(f"Profile data: {prof_res.text}")

if prof_res.status_code != 200:
    print("CRITICAL ERROR: Failed to log in / authenticate throwaway account.")
    sys.exit(1)

user_profile = prof_res.json().get("user", {})
user_id = user_profile.get("id")
print(f"Authenticated as user_id: {user_id}")

# Step 3: Query /api/analyses BEFORE upload
print("\n--- 3. Querying /api/analyses BEFORE Upload ---")
pre_analyses = session.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {pre_analyses.status_code}] GET /api/analyses: {pre_analyses.text}")

# Step 4: Upload an Analysis as Authenticated User
print("\n--- 4. Uploading Analysis via POST /api/analyze ---")
sample_resume_content = f"""John Probe Doe
Software Engineer
Email: {test_email}
Skills: Python, Flask, PostgreSQL, React, JavaScript, AWS

Work Experience:
Senior Backend Developer | TechCorp (2021 - Present)
- Architected REST APIs serving 500,000 daily active users using Python and Flask.
- Reduced database query latency by 45% by optimizing SQL queries and indexes.
- Deployed microservices on AWS Elastic Beanstalk and Docker.

Education:
B.S. Computer Science | University of Technology (2017 - 2021)
""".encode("utf-8")

files = {
    "resume": (f"Probe_Resume_{timestamp}.txt", sample_resume_content, "text/plain")
}
data = {
    "job_description": "Senior Python Backend Developer with database optimization experience."
}

upload_res = session.post(f"{BASE_URL}/api/analyze", files=files, data=data, timeout=30)
print(f"[HTTP {upload_res.status_code}] POST /api/analyze")
upload_json = {}
try:
    upload_json = upload_res.json()
    print(f"Analysis Response Keys: {list(upload_json.keys())}")
    print(f"Returned Analysis ID: {upload_json.get('id')}")
    print(f"Returned Resume ID: {upload_json.get('resume_id')}")
    print(f"Returned Overall Score: {upload_json.get('overall_score')}")
except Exception as e:
    print(f"Raw Response Body: {upload_res.text[:500]}")

analysis_id_returned = upload_json.get("id")

# Step 5: Query /api/analyses IMMEDIATELY after upload
print("\n--- 5. Querying /api/analyses IMMEDIATELY After Upload ---")
post_analyses = session.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {post_analyses.status_code}] GET /api/analyses: {post_analyses.text}")

# Step 6: Wait 3 seconds and query /api/analyses again
print("\n--- 6. Waiting 3 seconds & re-querying /api/analyses (Testing persistence across serverless invocations) ---")
time.sleep(3)
re_analyses = session.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {re_analyses.status_code}] GET /api/analyses: {re_analyses.text}")

# Step 7: Query /api/resumes
print("\n--- 7. Querying /api/resumes ---")
resumes_res = session.get(f"{BASE_URL}/api/resumes", timeout=10)
print(f"[HTTP {resumes_res.status_code}] GET /api/resumes: {resumes_res.text}")

# Step 8: Log out and Log back in
print("\n--- 8. Logging Out and Logging Back In ---")
session.post(f"{BASE_URL}/logout", timeout=10)
print(f"Cookies after logout: {session.cookies.get_dict()}")

login_res = session.post(
    f"{BASE_URL}/login",
    data={"email": test_email, "password": test_pass},
    allow_redirects=True,
    timeout=10
)
print(f"[HTTP {login_res.status_code}] POST /login -> Final URL: {login_res.url}")

post_login_analyses = session.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {post_login_analyses.status_code}] GET /api/analyses after re-login: {post_login_analyses.text}")

# Step 9: Duplicate probe user creation to test ID persistence / database engine
print("\n--- 9. Duplicate User Probe (Testing user ID continuity across connections) ---")
timestamp2 = int(time.time()) + 1
test_email2 = f"probe_user_{timestamp2}@jobspike-test.com"
session2 = requests.Session()
reg_res2 = session2.post(
    f"{BASE_URL}/register",
    data={"name": f"Probe User {timestamp2}", "email": test_email2, "password": test_pass},
    allow_redirects=True,
    timeout=10
)
prof_res2 = session2.get(f"{BASE_URL}/api/user/profile", timeout=10)
user_id2 = prof_res2.json().get("user", {}).get("id")
print(f"Second user registered. First User ID: {user_id}, Second User ID: {user_id2}")

print("==========================================================")
