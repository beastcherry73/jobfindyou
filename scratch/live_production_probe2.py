import os
import sys
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "https://www.jobspike.in"

print("==========================================================")
print("   VERCEL PRODUCTION POSTGRESQL PROBE (www.jobspike.in)   ")
print("==========================================================")

# Step 1: Probe base homepage
print("\n--- 1. Testing Homepage / Server Status ---")
try:
    res = requests.get(BASE_URL, timeout=10)
    print(f"[HTTP {res.status_code}] GET {BASE_URL}")
    print(f"X-Vercel-Id: {res.headers.get('X-Vercel-Id')}")
except Exception as e:
    print(f"FAILED to reach {BASE_URL}: {e}")
    sys.exit(1)

# Step 2: Single User Registration & Session Test
session1 = requests.Session()
session1.headers.update({"User-Agent": "JobSpike-Production-Probe/2.0"})

timestamp = int(time.time())
test_email1 = f"pg_probe_u1_{timestamp}@jobspike-test.com"
test_pass = "TestPass123!@#"
test_name1 = f"PG User 1 ({timestamp})"

print(f"\n--- 2. Registering Primary Test User ({test_email1}) ---")
reg_res1 = session1.post(
    f"{BASE_URL}/register",
    data={"name": test_name1, "email": test_email1, "password": test_pass},
    allow_redirects=True,
    timeout=10
)
print(f"[HTTP {reg_res1.status_code}] POST /register -> {reg_res1.url}")

prof_res1 = session1.get(f"{BASE_URL}/api/user/profile", timeout=10)
print(f"[HTTP {prof_res1.status_code}] GET /api/user/profile")
profile1 = prof_res1.json().get("user", {})
u1_id = profile1.get("id")
print(f"User 1 Assigned ID: {u1_id} (Created At: {profile1.get('created_at')})")

# Step 3: Analysis Upload Test
print("\n--- 3. Uploading Resume & Creating Analysis ---")
sample_resume = f"""Alex Pg Probe
Senior Backend Engineer
Email: {test_email1}
Skills: Python, PostgreSQL, Supabase, Flask, AWS, Docker

Work Experience:
Lead Backend Systems Engineer | CloudCorp (2022 - Present)
- Designed highly scalable REST microservices using Python Flask and PostgreSQL.
- Handled 2,000,000 requests per day with 99.99% uptime.
- Optimized database indexes reducing query latency by 60%.

Education:
B.S. Software Engineering | State University (2018 - 2022)
""".encode("utf-8")

files = {"resume": (f"PG_Probe_Resume_{timestamp}.txt", sample_resume, "text/plain")}
data = {"job_description": "Senior Backend Engineer with PostgreSQL experience."}

upload_res = session1.post(f"{BASE_URL}/api/analyze", files=files, data=data, timeout=30)
print(f"[HTTP {upload_res.status_code}] POST /api/analyze")
upload_data = {}
try:
    upload_data = upload_res.json()
    analysis_id = upload_data.get("id")
    resume_id = upload_data.get("resume_id")
    print(f"Analysis Created - Returned ID: {analysis_id}, Resume ID: {resume_id}, Score: {upload_data.get('overall_score')}")
except Exception as e:
    print(f"Upload response parsing error: {e}")
    print(f"Raw output: {upload_res.text[:400]}")

# Step 4: Verification of /api/analyses
print("\n--- 4. Querying /api/analyses Immediately ---")
get_an1 = session1.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {get_an1.status_code}] GET /api/analyses: {get_an1.text}")

print("\n--- 5. Waiting 5 Seconds & Re-Querying /api/analyses (Cross-Invocation Test) ---")
time.sleep(5)
get_an2 = session1.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {get_an2.status_code}] GET /api/analyses: {get_an2.text}")

# Step 5: Logout & Re-login Test
print("\n--- 6. Logging Out & Re-logging In ---")
session1.post(f"{BASE_URL}/logout", timeout=10)

login_res = session1.post(
    f"{BASE_URL}/login",
    data={"email": test_email1, "password": test_pass},
    allow_redirects=True,
    timeout=10
)
print(f"[HTTP {login_res.status_code}] POST /login -> {login_res.url}")

get_an3 = session1.get(f"{BASE_URL}/api/analyses", timeout=10)
print(f"[HTTP {get_an3.status_code}] GET /api/analyses after re-login: {get_an3.text}")

# Step 6: Parallel Multi-Threaded Registration Probe (Testing ID Isolation vs Shared Database)
print("\n--- 7. Concurrent Parallel Registration Probe (8 Parallel Workers) ---")

def register_worker(worker_id):
    s = requests.Session()
    w_email = f"parallel_w{worker_id}_{timestamp}@jobspike-test.com"
    try:
        r = s.post(
            f"{BASE_URL}/register",
            data={"name": f"Worker {worker_id}", "email": w_email, "password": test_pass},
            timeout=10
        )
        p = s.get(f"{BASE_URL}/api/user/profile", timeout=10)
        p_json = p.json() if p.status_code == 200 else {}
        uid = p_json.get("user", {}).get("id")
        return {"worker": worker_id, "status": r.status_code, "user_id": uid, "email": w_email}
    except Exception as err:
        return {"worker": worker_id, "error": str(err)}

workers_results = []
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(register_worker, i) for i in range(1, 9)]
    for f in futures:
        workers_results.append(f.result())

print("Parallel Registration Results:")
uids_seen = []
for res in sorted(workers_results, key=lambda x: x.get("worker", 0)):
    uid = res.get("user_id")
    uids_seen.append(uid)
    print(f"  Worker {res.get('worker')}: HTTP {res.get('status')} -> Assigned User ID: {uid}")

print(f"\nAll User IDs Assigned: {uids_seen}")
unique_uids = set(uids_seen)
if None not in unique_uids and len(unique_uids) == len(uids_seen):
    print("PROBE RESULT: 100% UNIQUE INCREMENTING USER IDs DETECTED ACROSS ALL PARALLEL INSTANCES!")
    print("This indicates all serverless instances are writing to a single shared central database!")
else:
    print(f"PROBE RESULT: DUPLICATE OR MISSING USER IDs DETECTED ({len(unique_uids)} unique out of {len(uids_seen)})")

print("\n==========================================================")
