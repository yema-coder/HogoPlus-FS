"""v1.0.25 live sandbox smoke tests (Presence Phase 1 + account deletion + privacy).

Runs against EXPO_PUBLIC_BACKEND_URL. Does NOT use pytest DB fixtures — pure HTTP.
"""
import os
import re
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")
DEMO_CGM_PHONE = "+919123456789"
WORKER_PHONE = "+917972540971"
OTP = "123456"


def _login(phone: str) -> str:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    # send-otp may 200 or be throttled 429 — we don't need the send for demo/whitelist phones
    r = s.post(f"{BASE}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, f"login failed {phone}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_cgm_token():
    return _login(DEMO_CGM_PHONE)


@pytest.fixture(scope="module")
def worker_token():
    return _login(WORKER_PHONE)


# 1) Public privacy policy — HTML with Marathi section
def test_privacy_policy_public():
    r = requests.get(f"{BASE}/api/legal/privacy", timeout=15)
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "गोपनीयता धोरण" in body, "Marathi section missing"


# 2) Demo account is protected — delete-account/request returns 409 demo_protected
def test_delete_account_request_demo_protected(demo_cgm_token):
    r = requests.post(
        f"{BASE}/api/auth/delete-account/request",
        headers={"Authorization": f"Bearer {demo_cgm_token}"},
        timeout=15,
    )
    assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
    j = r.json()
    detail = j.get("detail")
    code = detail.get("code") if isinstance(detail, dict) else detail
    assert code == "demo_protected", f"expected demo_protected, got {j}"


# 3) Worker /api/presence/my-status returns expected fields
def test_presence_my_status_worker(worker_token):
    r = requests.get(
        f"{BASE}/api/presence/my-status",
        headers={"Authorization": f"Bearer {worker_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("enabled", "in_pilot", "stop_after"):
        assert key in body, f"missing key {key} in {body}"


# 4) Demo CGM /api/presence/live — run demo-simulate first if empty
def test_presence_live_demo_cgm(demo_cgm_token):
    h = {"Authorization": f"Bearer {demo_cgm_token}"}
    r = requests.get(f"{BASE}/api/presence/live", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("enabled") and (body.get("counts", {}).get("tracking", 0) == 0):
        # Prime the demo bubble
        s = requests.post(f"{BASE}/api/presence/demo-simulate", headers=h, timeout=20)
        assert s.status_code == 200, s.text
        r = requests.get(f"{BASE}/api/presence/live", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
    for key in ("counts", "zones", "workers", "enabled"):
        assert key in body, f"missing key {key} in body keys={list(body.keys())}"
    # Counts should have the expected keys per spec
    counts = body["counts"]
    for k in ("tracking", "in_zone", "gps_inside", "gps_outside", "no_signal", "not_tracked", "stopped"):
        assert k in counts, f"counts missing {k}: {counts}"
