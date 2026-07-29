import os
import time
import requests
from flask import current_app

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

BUCKET_NAME = "resumes-private"


def is_supabase_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }


def ensure_bucket_exists():
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/storage/v1/bucket"
        res = requests.get(url, headers=get_headers(), timeout=5)
        if res.status_code == 200:
            buckets = [b.get("id") for b in res.json() if isinstance(b, dict)]
            if BUCKET_NAME not in buckets:
                # Create private bucket
                create_url = f"{SUPABASE_URL}/storage/v1/bucket"
                payload = {
                    "id": BUCKET_NAME,
                    "name": BUCKET_NAME,
                    "public": False
                }
                requests.post(create_url, headers=get_headers(), json=payload, timeout=5)
            return True
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Supabase bucket check warning: {e}")
    return False


def upload_resume_to_storage(file_stream, user_id, original_filename):
    """
    Streams uploaded PDF/TXT resume to Supabase Private Storage bucket.
    Returns relative file_path (e.g., 'user_1/1784910283_resume.pdf').
    """
    if not is_supabase_configured():
        return None

    try:
        ensure_bucket_exists()
        clean_name = "".join([c for c in original_filename if c.isalnum() or c in (".", "_", "-")]).strip()
        file_path = f"user_{user_id}/{int(time.time())}_{clean_name}"
        
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{file_path}"
        headers = get_headers()
        headers["Content-Type"] = "application/octet-stream"
        
        file_stream.seek(0)
        file_data = file_stream.read()
        file_stream.seek(0)

        res = requests.post(url, headers=headers, data=file_data, timeout=10)
        if res.status_code in (200, 201):
            return file_path
        else:
            if current_app:
                current_app.logger.warning(f"Supabase Storage Upload failed ({res.status_code}): {res.text}")
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Error uploading to Supabase Storage: {e}")
    return None


def get_signed_resume_url(file_path, expires_in=3600):
    """
    Generates short-lived signed URL for private resume access (default 60 mins).
    """
    if not is_supabase_configured() or not file_path:
        return None

    try:
        url = f"{SUPABASE_URL}/storage/v1/object/sign/{BUCKET_NAME}/{file_path}"
        payload = {"expiresIn": expires_in}
        res = requests.post(url, headers=get_headers(), json=payload, timeout=5)
        if res.status_code == 200:
            data = res.json()
            signed_path = data.get("signedURL") or data.get("signedUrl")
            if signed_path:
                if signed_path.startswith("http"):
                    return signed_path
                return f"{SUPABASE_URL}/storage/v1{signed_path}"
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Error generating signed URL: {e}")
    return None
