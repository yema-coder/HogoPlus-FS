"""
Phase 5 live scope smoke — MD Command Center role scoping (Manager vs CGM).
Runs against the external EXPO_PUBLIC_BACKEND_URL (production ingress).

Verifies (per review-request DoD):
  - CGM login → /api/dashboard/overview has 13 departments
  - Manager login (ENGINEERING) → overview has ONLY ENGINEERING
  - Manager blocked at cross-dept endpoint /api/dashboard/department/PRODUCTION (403)
  - Manager blocked at /api/dashboard/reports and /api/dashboard/audit (403)
  - Manager blocked at /api/admin/employees (403); CGM 200
  - Worker login gets rank>3 (dashboard client will show access-denied)
"""
import os
import time

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")

CGM_PHONE = "+918483029039"
ENG_MGR_PHONE = "+919834705825"
WORKER_PHONE = "+917972540971"
OTP = "123456"


def _login(phone: str) -> dict:
    """Returns access token + profile. Skips on rate-limit rather than failing."""
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    if r.status_code == 429:
        pytest.skip(f"rate limited for {phone}: {r.text}")
    assert r.status_code == 200, f"send-otp failed for {phone}: {r.status_code} {r.text}"
    time.sleep(0.3)
    v = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert v.status_code == 200, f"verify-otp failed for {phone}: {v.status_code} {v.text}"
    body = v.json()
    assert body.get("access_token"), f"no access_token in response: {body}"
    return body


@pytest.fixture(scope="module")
def cgm_token():
    return _login(CGM_PHONE)


@pytest.fixture(scope="module")
def eng_mgr_token():
    return _login(ENG_MGR_PHONE)


@pytest.fixture(scope="module")
def worker_token():
    return _login(WORKER_PHONE)


def _auth(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


# ---- CGM scope ----

class TestCGMScope:
    def test_cgm_overview_has_13_departments(self, cgm_token):
        r = requests.get(f"{BASE}/api/dashboard/overview", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "departments" in data
        assert len(data["departments"]) == 13, f"expected 13 depts, got {len(data['departments'])}"
        codes = {d["code"] for d in data["departments"]}
        assert "ENGINEERING" in codes
        assert "PRODUCTION" in codes

    def test_cgm_can_read_any_department(self, cgm_token):
        r = requests.get(f"{BASE}/api/dashboard/department/PRODUCTION", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("code") == "PRODUCTION" or "attendance" in r.json()

    def test_cgm_reports_endpoint(self, cgm_token):
        r = requests.get(f"{BASE}/api/dashboard/reports", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text
        assert "reports" in r.json()

    def test_cgm_audit_endpoint(self, cgm_token):
        r = requests.get(f"{BASE}/api/dashboard/audit", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text

    def test_cgm_admin_employees_search(self, cgm_token):
        r = requests.get(f"{BASE}/api/admin/employees?search=Mhaske", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 1
        assert any("Mhaske" in (e.get("full_name") or "") for e in rows)

    def test_cgm_approvals_endpoint(self, cgm_token):
        r = requests.get(f"{BASE}/api/dashboard/approvals", headers=_auth(cgm_token), timeout=20)
        assert r.status_code == 200, r.text


# ---- Manager scope ----

class TestManagerScope:
    def test_eng_mgr_overview_only_engineering(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/dashboard/overview", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        depts = data.get("departments", [])
        assert len(depts) == 1, f"Manager must see exactly 1 dept, got {len(depts)}: {[d['code'] for d in depts]}"
        assert depts[0]["code"] == "ENGINEERING"

    def test_eng_mgr_blocked_on_other_department(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/dashboard/department/PRODUCTION", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 403, f"expected 403 for cross-dept, got {r.status_code}: {r.text}"

    def test_eng_mgr_can_read_own_department(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/dashboard/department/ENGINEERING", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 200, r.text

    def test_eng_mgr_blocked_on_reports(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/dashboard/reports", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_eng_mgr_blocked_on_audit(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/dashboard/audit", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_eng_mgr_blocked_on_admin_employees(self, eng_mgr_token):
        r = requests.get(f"{BASE}/api/admin/employees?search=Mhaske", headers=_auth(eng_mgr_token), timeout=20)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ---- Worker scope ----

class TestWorkerScope:
    def test_worker_profile_rank_is_worker(self, worker_token):
        r = requests.get(f"{BASE}/api/auth/me", headers=_auth(worker_token), timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        role = me.get("role") or {}
        assert (role.get("rank") or 99) > 3, f"expected worker rank>3, got role={role}"

    def test_worker_blocked_on_overview(self, worker_token):
        r = requests.get(f"{BASE}/api/dashboard/overview", headers=_auth(worker_token), timeout=15)
        assert r.status_code in (401, 403), f"expected worker denied on overview, got {r.status_code}: {r.text}"
