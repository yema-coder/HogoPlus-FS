"""Live public-URL spot-checks for Prompt 7 backend endpoints.
Uses EXPO_PUBLIC_BACKEND_URL (public preview). Non-destructive.
"""
import os
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")
CGM_PHONE = "+918483029039"
TIME_MGR_PHONE = "+918308829567"
WORKER_PHONE = "+917972540971"
OTP = "123456"


def _login(phone):
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    # rate-limit tolerated; verify still works with demo OTP for seeded phones
    r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, f"login {phone}: {r.status_code} {r.text}"
    return r.json()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_cgm_login_and_get_time_office_manager_id():
    cgm = _login(CGM_PHONE)
    assert cgm["access_token"]
    # search employees for TIME_OFFICE mgr (+918308829567)
    r = requests.get(f"{BASE}/api/admin/employees?phone={TIME_MGR_PHONE.replace('+', '%2B')}",
                     headers=_headers(cgm["access_token"]), timeout=15)
    # admin endpoint may differ; fallback: query via /api/admin/employees?q=
    if r.status_code != 200:
        r = requests.get(f"{BASE}/api/admin/employees?q=8308829567",
                         headers=_headers(cgm["access_token"]), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    if isinstance(data, list):
        items = data
    else:
        items = data.get("items") or data.get("results") or []
    match = [e for e in items if e.get("phone") == TIME_MGR_PHONE]
    assert match, f"TIME_OFFICE mgr not found in {items[:3]}"
    return cgm["access_token"], match[0]["id"], match[0].get("emp_id")


def test_set_password_and_password_login_role_gate():
    cgm_tok, tmgr_id, tmgr_emp = test_cgm_login_and_get_time_office_manager_id()

    # (1) CGM sets a fresh temp password for TIME_OFFICE manager
    r = requests.post(
        f"{BASE}/api/admin/employees/{tmgr_id}/set-password",
        json={"password": "TestTmp1234"},
        headers=_headers(cgm_tok), timeout=15,
    )
    assert r.status_code == 200, f"set-password should succeed for CGM: {r.status_code} {r.text}"
    print(f"[OK] CGM set-password 200 for TIME_OFFICE mgr emp_id={tmgr_emp}")

    # (2) password-login with that manager (rank 3) → expect 403 (MD/CGM only)
    r = requests.post(
        f"{BASE}/api/auth/password-login",
        json={"emp_id": tmgr_emp, "password": "TestTmp1234"},
        timeout=15,
    )
    assert r.status_code == 403, f"rank-3 mgr password-login should be 403: {r.status_code} {r.text}"
    print(f"[OK] password-login 403 for rank-3 manager (MD/CGM only enforced)")

    # (3) set-password by a rank-3 manager token → 403
    tmgr_login = _login(TIME_MGR_PHONE)
    r = requests.post(
        f"{BASE}/api/admin/employees/{tmgr_id}/set-password",
        json={"password": "AttackPass1"},
        headers=_headers(tmgr_login["access_token"]), timeout=15,
    )
    assert r.status_code == 403, f"rank-3 mgr set-password should be 403: {r.status_code} {r.text}"
    print(f"[OK] set-password 403 by rank-3 manager token")


def test_plates_search_public():
    cgm = _login(CGM_PHONE)
    r = requests.get(f"{BASE}/api/dashboard/plates/search?q=MH14",
                     headers=_headers(cgm["access_token"]), timeout=15)
    assert r.status_code == 200, r.text
    results = r.json().get("results", [])
    assert any(x.get("plate", "").startswith("MH14") for x in results), f"MH14 plate not found: {results}"
    print(f"[OK] plates/search q=MH14 → {len(results)} result(s)")


def test_worker_password_login_forbidden():
    # try password-login on a worker emp_id (should be 401 no password or 403 role)
    r = requests.post(
        f"{BASE}/api/auth/password-login",
        json={"emp_id": "0021", "password": "anything"},
        timeout=15,
    )
    assert r.status_code in (401, 403), f"worker password-login should reject: {r.status_code} {r.text}"
    print(f"[OK] worker password-login → {r.status_code}")


if __name__ == "__main__":
    test_set_password_and_password_login_role_gate()
    test_plates_search_public()
    test_worker_password_login_forbidden()
    print("\nALL LIVE PROMPT7 CHECKS PASSED")
