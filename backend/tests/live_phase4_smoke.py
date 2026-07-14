"""Live Phase-4 smoke tests hitting the external EXPO_PUBLIC_BACKEND_URL.

Runs sequentially so we reuse tokens (send-otp is 3/10min per phone).
"""
import os
import time

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

PHONES = {
    "time_mgr": "+918308829567",
    "cgm": "+918483029039",
    "eng_mgr": "+919834705825",
    "eng_worker": "+917775915271",
}

_tokens: dict[str, str] = {}


def _login(phone: str) -> str:
    if phone in _tokens:
        return _tokens[phone]
    r = requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=30)
    assert r.status_code == 200, f"send-otp failed for {phone}: {r.status_code} {r.text}"
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=30)
    assert r.status_code == 200, f"verify-otp failed for {phone}: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    _tokens[phone] = token
    return token


def H(phone: str) -> dict:
    return {"Authorization": f"Bearer {_login(phone)}"}


# ---------------------- Attendance flagged ----------------------

def test_flagged_face_mismatch_row_with_presigned_urls():
    r = requests.get(f"{API}/attendance/flagged", headers=H(PHONES["time_mgr"]), timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    # find the row for emp 0056
    target = None
    for row in rows:
        if row.get("employee", {}).get("emp_id") == "0056" or row.get("emp_id") == "0056":
            target = row
            break
        # fallback: check for face_match_score 41.5
        if row.get("face_match_score") == 41.5:
            target = row
            break
    assert target is not None, f"No face_mismatch row found for emp 0056. Rows: {[r.get('employee', r) for r in rows]}"
    assert target.get("face_match_score") == 41.5, target
    assert target.get("face_verified") is False, target
    assert target.get("flagged_reason") == "face_mismatch", target
    selfie_url = target.get("selfie_url")
    ref_url = target.get("reference_selfie_url")
    assert selfie_url and selfie_url.startswith("https://"), f"selfie_url not https presigned: {selfie_url}"
    assert ref_url and ref_url.startswith("https://"), f"reference_selfie_url not https presigned: {ref_url}"

    # HEAD-fetch both URLs (avoid downloading full body)
    for label, url in (("selfie", selfie_url), ("reference", ref_url)):
        rr = requests.get(url, timeout=30, stream=True)
        rr.close()
        assert rr.status_code == 200, f"{label} URL returned {rr.status_code}"
        ctype = rr.headers.get("content-type", "")
        assert ctype.startswith("image/"), f"{label} content-type not image/*: {ctype!r}"
        print(f"OK {label}: {rr.status_code} {ctype}")


# ---------------------- Admin AI usage ----------------------

def test_ai_usage_worker_forbidden():
    r = requests.get(f"{API}/admin/ai-usage", headers=H(PHONES["eng_worker"]), timeout=30)
    assert r.status_code == 403, r.status_code


def test_ai_usage_cgm_ok():
    r = requests.get(f"{API}/admin/ai-usage", headers=H(PHONES["cgm"]), timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "counts" in data
    assert "rekognition_failures" in data


# ---------------------- Admin backup-now ----------------------

def test_backup_now_cgm():
    r = requests.post(f"{API}/admin/backup-now", headers=H(PHONES["cgm"]), timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "uploaded" in data, data
    assert data["uploaded"].startswith("backups/") and data["uploaded"].endswith(".sql.gz"), data
    assert "kept" in data
    assert "deleted" in data


# ---------------------- SOP docs list ----------------------

def test_sop_docs_list_has_boiler():
    r = requests.get(f"{API}/admin/sop-docs", headers=H(PHONES["cgm"]), timeout=30)
    assert r.status_code == 200, r.text
    docs = r.json()
    boiler = [d for d in docs if d.get("title") == "test_sop_boiler"]
    assert boiler, f"test_sop_boiler doc missing. Titles: {[d.get('title') for d in docs]}"
    d = boiler[0]
    assert d.get("status") == "ready", d
    assert d.get("chunk_count") == 2, d


# ---------------------- SOP chat (live LLM) ----------------------

def test_ai_chat_boiler_pressure_grounded():
    r = requests.post(
        f"{API}/ai/chat",
        json={"message": "What is the boiler safety valve set pressure?"},
        headers=H(PHONES["cgm"]),
        timeout=90,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "answer" in data, data
    assert "10.5" in data["answer"], f"answer missing 10.5: {data['answer']}"
    citations = data.get("citations", [])
    assert citations, f"no citations returned: {data}"
    titles = [c.get("doc_title") for c in citations]
    assert "test_sop_boiler" in titles, f"test_sop_boiler not in citations: {titles}"


# ---------------------- ANPR / gauge auth+404 ----------------------

def test_anpr_no_token_401():
    r = requests.post(f"{API}/ai/anpr", json={"photo_key": "does-not-exist.jpg"}, timeout=30)
    assert r.status_code in (401, 403), r.status_code


def test_anpr_nonexistent_photo_404():
    r = requests.post(
        f"{API}/ai/anpr",
        json={"photo_key": f"nope-{int(time.time())}.jpg"},
        headers=H(PHONES["cgm"]),
        timeout=30,
    )
    assert r.status_code == 404, r.text


def test_gauge_no_token_401():
    r = requests.post(f"{API}/ai/gauge-read", json={"photo_key": "x.jpg"}, timeout=30)
    assert r.status_code in (401, 403), r.status_code


def test_gauge_nonexistent_photo_404():
    r = requests.post(
        f"{API}/ai/gauge-read",
        json={"photo_key": f"nope-g-{int(time.time())}.jpg", "expected_min": 0, "expected_max": 100},
        headers=H(PHONES["cgm"]),
        timeout=30,
    )
    assert r.status_code == 404, r.text
