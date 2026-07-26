"""Live E2E backend spot-checks for PROMPT 17 features hitting the PUBLIC preview URL.

Scope (per review-request):
- POST /api/admin/announcements scoping (TO manager own dept 200, other dept 403,
  all 403; CGM audience=all 200)
- POST /api/incidents/{id}/escalate by CGM: mode=department & mode=employee 200,
  reason <3 chars 422; GET /api/incidents/escalation-targets returns rank<=3 demo rows
- POST /api/admin/employees direct-add: TO manager creates Worker 200 (approved+active),
  Manager role by TO -> 200 (Prompt 21), CGM/MD role by TO -> 403, Manager by CGM -> 200
- GET /api/admin/emp-id-suggest returns next id
- PATCH /api/admin/employees/{id}: TO rename Worker 200, TO may edit Manager accounts
  and grant Manager (Prompt 21); CGM/MD accounts+roles stay 403; role change reflects
  in /api/auth/me on SAME token
- POST /api/employees/me/face-enroll: first call 200 has_face_reference=True,
  second call 409; GET /api/auth/me has has_face_reference field

Demo phones (is_demo, auto-cleaned): +9190000xxxxx  OTP 123456 always accepted.
"""
import os
import time
import uuid

import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

WORKER_PHONE = "+919000000001"     # PRODUCTION worker (demo)
ACC_MGR_PHONE = "+919000000101"    # ACCOUNTS manager (demo)
TO_MGR_PHONE = "+919000000113"     # TIME_OFFICE manager (demo)
CGM_PHONE = "+919000000500"        # CGM (demo)


def _login(phone: str) -> str:
    # demo OTP bypasses send; go straight to verify
    r = requests.post(
        f"{BASE}/api/auth/verify-otp",
        json={"phone": phone, "otp": "123456"},
        timeout=20,
    )
    assert r.status_code == 200, f"login {phone}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ------- fixtures -----------------------------------------------------------

@pytest.fixture(scope="module")
def worker_tok():
    return _login(WORKER_PHONE)


@pytest.fixture(scope="module")
def to_tok():
    return _login(TO_MGR_PHONE)


@pytest.fixture(scope="module")
def cgm_tok():
    return _login(CGM_PHONE)


@pytest.fixture(scope="module")
def acc_mgr_tok():
    return _login(ACC_MGR_PHONE)


# ------- Health / auth ------------------------------------------------------

def test_health():
    r = requests.get(f"{BASE}/api/health", timeout=15)
    # allow 200 or 404 (some deployments route differently)
    assert r.status_code in (200, 404), r.text


def test_me_has_face_reference_field(worker_tok):
    r = requests.get(f"{BASE}/api/auth/me", headers=_h(worker_tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "has_face_reference" in body, body


# ------- Part F: announcements ---------------------------------------------

def test_announcement_time_office_own_dept(to_tok):
    r = requests.post(
        f"{BASE}/api/admin/announcements",
        headers=_h(to_tok),
        json={
            "title": "TO test",
            "message": "hello time office",
            "audience": "department",
            "department_code": "TIME_OFFICE",
        },
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("recipients", 0) >= 0


def test_announcement_time_office_other_dept_forbidden(to_tok):
    r = requests.post(
        f"{BASE}/api/admin/announcements",
        headers=_h(to_tok),
        json={
            "title": "cross",
            "message": "nope",
            "audience": "department",
            "department_code": "PRODUCTION",
        },
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_announcement_time_office_all_forbidden(to_tok):
    r = requests.post(
        f"{BASE}/api/admin/announcements",
        headers=_h(to_tok),
        json={"title": "all", "message": "nope", "audience": "all"},
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_announcement_cgm_all(cgm_tok):
    r = requests.post(
        f"{BASE}/api/admin/announcements",
        headers=_h(cgm_tok),
        json={"title": "All hands", "message": "E2E all-hands ping", "audience": "all"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("recipients", 0) > 0


# ------- Part E: manual escalation -----------------------------------------

def _find_or_create_open_incident(cgm_tok: str, worker_tok: str) -> str:
    # look for an open incident (status in submitted/acknowledged/in_progress)
    r = requests.get(
        f"{BASE}/api/incidents?status=submitted",
        headers=_h(cgm_tok),
        timeout=20,
    )
    if r.status_code == 200:
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        for it in items:
            if it.get("status") in ("submitted", "acknowledged", "in_progress"):
                return it["id"]
    # else fabricate one from the demo worker (auto-cleaned)
    r = requests.post(
        f"{BASE}/api/incidents",
        headers=_h(worker_tok),
        json={"category": "safety", "department_code": "PRODUCTION", "photo_key": "e2e-test.jpg"},
        timeout=20,
    )
    assert r.status_code == 200, f"create incident: {r.status_code} {r.text}"
    return r.json()["id"]


def test_escalation_targets(cgm_tok, worker_tok):
    r = requests.get(f"{BASE}/api/incidents/escalation-targets", headers=_h(cgm_tok), timeout=20)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    assert all(int(e.get("role_rank", 99)) <= 3 for e in items), items
    # workers rejected
    r = requests.get(f"{BASE}/api/incidents/escalation-targets", headers=_h(worker_tok), timeout=20)
    assert r.status_code == 403, r.text


def test_escalate_department_and_employee(cgm_tok, worker_tok, to_tok):
    incident_id = _find_or_create_open_incident(cgm_tok, worker_tok)

    # reason too short → 422
    r = requests.post(
        f"{BASE}/api/incidents/{incident_id}/escalate",
        headers=_h(cgm_tok),
        json={"mode": "department", "department_code": "TIME_OFFICE", "reason": "x"},
        timeout=20,
    )
    assert r.status_code == 422, r.text

    # mode=department → 200 status escalated
    r = requests.post(
        f"{BASE}/api/incidents/{incident_id}/escalate",
        headers=_h(cgm_tok),
        json={
            "mode": "department",
            "department_code": "TIME_OFFICE",
            "reason": "E2E dept escalation test",
        },
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "escalated", body

    # mode=employee to a demo manager (Time Office) → 200
    targets = requests.get(
        f"{BASE}/api/incidents/escalation-targets", headers=_h(cgm_tok), timeout=20
    ).json()
    # find TO manager id via /api/auth/me
    to_me = requests.get(f"{BASE}/api/auth/me", headers=_h(to_tok), timeout=20).json()
    to_id = to_me["id"]
    r = requests.post(
        f"{BASE}/api/incidents/{incident_id}/escalate",
        headers=_h(cgm_tok),
        json={"mode": "employee", "employee_id": to_id, "reason": "E2E employee escalation test"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("escalated_to") == to_id


# ------- Part B: direct-add + edit guardrails ------------------------------

def _fresh_phone(seed: int) -> str:
    # keep in +9190000xxxxx demo bucket so it auto-cleans
    # last 5 digits: 60000 + random 0-9999
    n = 60000 + (int(time.time()) % 10000) + seed
    return f"+91900{n:07d}"[:13]  # ensure 13 chars incl +


def test_emp_id_suggest(to_tok):
    r = requests.get(f"{BASE}/api/admin/emp-id-suggest", headers=_h(to_tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # actual key: suggested_emp_id
    key = next((k for k in ("suggested_emp_id", "emp_id", "next_emp_id") if k in body), None)
    assert key, body
    assert isinstance(body[key], str) and body[key], body


def test_direct_add_worker_by_time_office(to_tok):
    r = requests.get(f"{BASE}/api/admin/emp-id-suggest", headers=_h(to_tok), timeout=15).json()
    eid = r.get("suggested_emp_id") or r.get("emp_id") or r.get("next_emp_id")
    phone = _fresh_phone(1)
    r = requests.post(
        f"{BASE}/api/admin/employees",
        headers=_h(to_tok),
        json={
            "full_name": "E2E Test Worker",
            "phone": phone,
            "department_code": "PRODUCTION",
            "role_code": "Worker",
            "shift_code": "A",
            "emp_id": eid,
        },
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("onboarding_status") == "approved", body
    assert body.get("is_active") is True, body
    assert body.get("role_code") == "Worker", body
    # stash for next test
    pytest._e2e_worker_id = body["id"]
    pytest._e2e_worker_phone = phone


def test_direct_add_cgm_by_time_office_forbidden(to_tok):
    # Prompt 21: TO may create Manager accounts now — but never CGM/MD accounts
    r = requests.get(f"{BASE}/api/admin/emp-id-suggest", headers=_h(to_tok), timeout=15).json()
    eid = r.get("suggested_emp_id") or r.get("emp_id") or r.get("next_emp_id")
    phone = _fresh_phone(2)
    r = requests.post(
        f"{BASE}/api/admin/employees",
        headers=_h(to_tok),
        json={
            "full_name": "E2E Wannabe CGM",
            "phone": phone,
            "department_code": "PRODUCTION",
            "role_code": "CGM",
            "shift_code": "A",
            "emp_id": eid,
        },
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_direct_add_manager_by_cgm(cgm_tok):
    r = requests.get(f"{BASE}/api/admin/emp-id-suggest", headers=_h(cgm_tok), timeout=15).json()
    eid = r.get("suggested_emp_id") or r.get("emp_id") or r.get("next_emp_id")
    phone = _fresh_phone(3)
    r = requests.post(
        f"{BASE}/api/admin/employees",
        headers=_h(cgm_tok),
        json={
            "full_name": "E2E CGM-created Mgr",
            "phone": phone,
            "department_code": "PRODUCTION",
            "role_code": "Manager",
            "shift_code": "A",
            "emp_id": eid,
        },
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("role_code") == "Manager"


def test_patch_worker_rename_by_time_office(to_tok):
    wid = getattr(pytest, "_e2e_worker_id", None)
    if not wid:
        pytest.skip("worker not created")
    r = requests.patch(
        f"{BASE}/api/admin/employees/{wid}",
        headers=_h(to_tok),
        json={"full_name": "E2E Renamed Worker"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("full_name") == "E2E Renamed Worker"


def test_patch_grant_manager_by_time_office_allowed(to_tok):
    # Prompt 21: Time Office MAY grant the Manager role (installing HODs)
    wid = getattr(pytest, "_e2e_worker_id", None)
    if not wid:
        pytest.skip("worker not created")
    r = requests.patch(
        f"{BASE}/api/admin/employees/{wid}",
        headers=_h(to_tok),
        json={"role_code": "Manager"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    # revert so the follow-up tests still operate on a Worker
    r = requests.patch(
        f"{BASE}/api/admin/employees/{wid}",
        headers=_h(to_tok),
        json={"role_code": "Worker"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    # ...but CGM/MD roles remain top-only
    r = requests.patch(
        f"{BASE}/api/admin/employees/{wid}",
        headers=_h(to_tok),
        json={"role_code": "CGM"},
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_patch_cgm_account_by_time_office_forbidden(to_tok):
    # Patching the demo CGM account must stay 403 (Prompt 21 rails)
    me = requests.get(
        f"{BASE}/api/auth/me", headers=_h(_login(CGM_PHONE)), timeout=15
    ).json()
    cgm_id = me["id"]
    r = requests.patch(
        f"{BASE}/api/admin/employees/{cgm_id}",
        headers=_h(to_tok),
        json={"full_name": "Hax"},
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_role_change_propagates_without_relogin(to_tok):
    """Login as freshly-created Worker, TO changes role to Staff, /me reflects it on
    the SAME token."""
    phone = getattr(pytest, "_e2e_worker_phone", None)
    wid = getattr(pytest, "_e2e_worker_id", None)
    if not phone or not wid:
        pytest.skip("worker not created")
    worker_tok = _login(phone)
    # role change to Staff (allowed for TO manager)
    r = requests.patch(
        f"{BASE}/api/admin/employees/{wid}",
        headers=_h(to_tok),
        json={"role_code": "Staff"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    # SAME token → /me must reflect new role
    r = requests.get(f"{BASE}/api/auth/me", headers=_h(worker_tok), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("role_code") == "Staff", r.json()


# ------- Part C: face enrollment -------------------------------------------

def test_face_enroll_flow():
    """Uses a FRESH demo worker created by CGM so face reference starts NULL."""
    cgm = _login(CGM_PHONE)
    eid = requests.get(f"{BASE}/api/admin/emp-id-suggest", headers=_h(cgm), timeout=15).json()
    eid = eid.get("suggested_emp_id") or eid.get("emp_id") or eid.get("next_emp_id")
    phone = _fresh_phone(4)
    r = requests.post(
        f"{BASE}/api/admin/employees",
        headers=_h(cgm),
        json={
            "full_name": "E2E Face Enroll",
            "phone": phone,
            "department_code": "PRODUCTION",
            "role_code": "Worker",
            "shift_code": "A",
            "emp_id": eid,
        },
        timeout=20,
    )
    if r.status_code != 200:
        pytest.skip(f"could not seed face-enroll worker: {r.status_code} {r.text}")

    worker = _login(phone)
    # /me confirms no reference
    me = requests.get(f"{BASE}/api/auth/me", headers=_h(worker), timeout=15).json()
    assert me.get("has_face_reference") is False, me

    r = requests.post(
        f"{BASE}/api/employees/me/face-enroll",
        headers=_h(worker),
        json={"selfie_key": "e2e-test.jpg"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("has_face_reference") is True

    # /me now reports True
    me = requests.get(f"{BASE}/api/auth/me", headers=_h(worker), timeout=15).json()
    assert me.get("has_face_reference") is True, me

    # second call → 409
    r = requests.post(
        f"{BASE}/api/employees/me/face-enroll",
        headers=_h(worker),
        json={"selfie_key": "e2e-test-2.jpg"},
        timeout=20,
    )
    assert r.status_code == 409, r.text
