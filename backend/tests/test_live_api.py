"""Live API end-to-end tests against the running backend (dev DB + Redis).

Runs against BASE_URL from EXPO_PUBLIC_BACKEND_URL. Uses the seeded 401 employees
and the demo OTP (123456). Does NOT reseed. Uses distinct worker phones per
attendance sub-test to avoid the (employee, day) unique-constraint collisions.
"""

import io
import os
import uuid
from typing import Any

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://hogo-backend-phase1.preview.emergentagent.com"
).rstrip("/")

API = f"{BASE_URL}/api"
DEMO_OTP = "123456"

# Well-known seeded phones
PH_CGM = "+919700000001"
PH_PROD_MGR = "+919700000002"
PH_ENG_MGR = "+919700000003"
PH_TIME_MGR = "+919700000005"
PH_PROD_WORKER = "+919700000078"       # Production worker (used for forms/incidents)
PH_ATT_VERIFIED_PLUS = "+919700000079"  # unique for attendance test 1
PH_ATT_VERIFIED = "+919700000080"      # unique for attendance test 2 (no beacon)
PH_ATT_FLAGGED = "+919700000081"       # unique for attendance test 3 (far coords)
PH_ATT_DUP = "+919700000082"           # unique for duplicate-punch test


# ------------------------- helpers -------------------------

def _login(phone: str) -> dict:
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": DEMO_OTP}, timeout=15)
    assert r.status_code == 200, f"verify-otp failed for {phone}: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body and body.get("is_new") is False
    return body


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def prod_mgr() -> dict:
    return _login(PH_PROD_MGR)


@pytest.fixture(scope="module")
def cgm() -> dict:
    return _login(PH_CGM)


@pytest.fixture(scope="module")
def time_mgr() -> dict:
    return _login(PH_TIME_MGR)


@pytest.fixture(scope="module")
def prod_worker() -> dict:
    return _login(PH_PROD_WORKER)


# ------------------------- health & auth -------------------------

class TestHealthAndAuth:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        assert r.json() == {"status": "healthy"}

    def test_send_otp_rate_limit(self):
        # Use a burner phone number; hit 4 times, expect 429 on 4th.
        phone = f"+919999{uuid.uuid4().int % 1000000:06d}"
        results = []
        for _ in range(4):
            r = requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=10)
            results.append(r.status_code)
        assert results[:3] == [200, 200, 200], f"expected 3x200 first, got {results}"
        assert results[3] == 429, f"expected 429 on 4th, got {results[3]}"

    def test_verify_otp_prod_manager(self, prod_mgr):
        assert prod_mgr["employee"]["phone"] == PH_PROD_MGR
        assert prod_mgr["employee"]["department_code"] == "PRODUCTION"
        assert prod_mgr["employee"]["role"]["rank"] == 3, prod_mgr["employee"]
        assert "access_token" in prod_mgr and "refresh_token" in prod_mgr

    def test_verify_otp_wrong_otp(self):
        # Use a phone unlikely to have hit failure lockout
        phone = f"+919888{uuid.uuid4().int % 1000000:06d}"
        r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "000000"}, timeout=10)
        assert r.status_code == 401, r.text

    def test_verify_otp_unknown_phone_new(self):
        phone = f"+919777{uuid.uuid4().int % 1000000:06d}"
        r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": DEMO_OTP}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json() == {"is_new": True}

    def test_refresh_and_me(self, prod_mgr):
        r = requests.post(f"{API}/auth/refresh", json={"refresh_token": prod_mgr["refresh_token"]}, timeout=10)
        assert r.status_code == 200
        new_pair = r.json()
        assert "access_token" in new_pair and "refresh_token" in new_pair

        r = requests.get(f"{API}/auth/me", headers=_auth(new_pair["access_token"]), timeout=10)
        assert r.status_code == 200
        assert r.json()["phone"] == PH_PROD_MGR


# ------------------------- departments -------------------------

class TestDepartments:
    def test_public_list(self):
        r = requests.get(f"{API}/departments", timeout=10)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) == 13, f"expected 13 depts, got {len(rows)}"
        first = rows[0]
        for k in ("code", "name_en", "name_hi", "name_mr"):
            assert k in first and first[k], f"missing/empty {k}"


# ------------------------- forms -------------------------

class TestForms:
    def test_worker_forms_scoped_to_dept(self, prod_worker):
        r = requests.get(f"{API}/forms", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        forms = r.json()
        assert forms, "expected at least one form for PRODUCTION"
        assert all(f["department_code"] == "PRODUCTION" for f in forms)

    def test_form_submit_happy_and_invalid(self, prod_worker, prod_mgr):
        # Find the hourly_process_log form
        r = requests.get(f"{API}/forms", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        forms = r.json()
        target = next((f for f in forms if f["code"] == "hourly_process_log"), None)
        assert target is not None, f"hourly_process_log not found; got {[f['code'] for f in forms]}"

        # Happy path
        payload = {
            "data_json": {"station": "pan", "reading_photo": "x.jpg", "brix_value": 50},
            "photos": ["x.jpg"],
            "gps_lat": None,
            "gps_lng": None,
        }
        r = requests.post(
            f"{API}/forms/{target['id']}/submit",
            headers=_auth(prod_worker["access_token"]),
            json=payload,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["status"] == "submitted"
        sub_id = sub["id"]

        # Invalid select option
        bad = {
            "data_json": {"station": "not_a_station", "reading_photo": "x.jpg", "brix_value": 50},
            "photos": [],
        }
        r = requests.post(
            f"{API}/forms/{target['id']}/submit",
            headers=_auth(prod_worker["access_token"]),
            json=bad,
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "errors" in (r.json().get("detail") or {}), r.text

        # Manager approval
        r = requests.post(
            f"{API}/submissions/{sub_id}/approve",
            headers=_auth(prod_mgr["access_token"]),
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    def test_worker_submissions_scoped(self, prod_worker):
        r = requests.get(f"{API}/submissions", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        me_id = _me_id(prod_worker["access_token"])
        assert all(s["submitted_by"] == me_id for s in items), "worker sees other people's submissions"


def _me_id(token: str) -> str:
    r = requests.get(f"{API}/auth/me", headers=_auth(token), timeout=10)
    assert r.status_code == 200
    return r.json()["id"]


# ------------------------- incidents -------------------------

class TestIncidents:
    def test_incident_create_and_timeline(self, prod_worker, prod_mgr, cgm):
        payload = {
            "category": "safety",
            "department_code": "PRODUCTION",
            "photo_key": "p.jpg",
            "gps_lat": 19.0,
            "gps_lng": 74.7,
        }
        r = requests.post(f"{API}/incidents", headers=_auth(prod_worker["access_token"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        inc = r.json()
        assert inc["assigned_manager_id"], "assigned_manager_id must be set"
        assert inc["status"] == "submitted"
        inc_id = inc["id"]

        # Timeline
        r = requests.get(f"{API}/incidents/{inc_id}", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        detail = r.json()
        events = [t["event"] for t in detail.get("timeline", [])]
        assert "created" in events, f"timeline missing 'created' event: {events}"

        # Worker attempts status change -> 403
        r = requests.post(
            f"{API}/incidents/{inc_id}/status",
            headers=_auth(prod_worker["access_token"]),
            json={"status": "seen"},
            timeout=10,
        )
        assert r.status_code == 403, r.text

        # Manager changes status -> 200 with new timeline entry
        r = requests.post(
            f"{API}/incidents/{inc_id}/status",
            headers=_auth(prod_mgr["access_token"]),
            json={"status": "seen"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/incidents/{inc_id}", headers=_auth(prod_mgr["access_token"]), timeout=10)
        events = [t["event"] for t in r.json()["timeline"]]
        assert "seen" in events, f"missing 'seen' after status change: {events}"

        # CGM should see all-dept incidents
        r = requests.get(f"{API}/incidents", headers=_auth(cgm["access_token"]), timeout=15)
        assert r.status_code == 200
        assert any(i["id"] == inc_id for i in r.json())


# ------------------------- attendance -------------------------

class TestAttendance:
    def test_punch_in_verified_plus(self):
        tok = _login(PH_ATT_VERIFIED_PLUS)["access_token"]
        payload = {"gps_lat": 19.0, "gps_lng": 74.7, "selfie_key": "s.jpg", "ble_beacon_id": "b1"}
        r = requests.post(f"{API}/attendance/punch-in", headers=_auth(tok), json=payload, timeout=15)
        # Allow 409 if a prior test run already punched in for same worker on same day
        if r.status_code == 409:
            pytest.skip("attendance already exists for today for this worker (persistent DB)")
        assert r.status_code == 200, r.text
        assert r.json()["verification_level"] == "verified_plus"

    def test_punch_in_verified_no_beacon(self):
        tok = _login(PH_ATT_VERIFIED)["access_token"]
        payload = {"gps_lat": 19.0, "gps_lng": 74.7, "selfie_key": "s.jpg"}
        r = requests.post(f"{API}/attendance/punch-in", headers=_auth(tok), json=payload, timeout=15)
        if r.status_code == 409:
            pytest.skip("attendance already exists for today for this worker")
        assert r.status_code == 200, r.text
        assert r.json()["verification_level"] == "verified"

    def test_punch_in_flagged_far(self):
        tok = _login(PH_ATT_FLAGGED)["access_token"]
        payload = {"gps_lat": 19.1, "gps_lng": 74.8, "selfie_key": "s.jpg"}
        r = requests.post(f"{API}/attendance/punch-in", headers=_auth(tok), json=payload, timeout=15)
        if r.status_code == 409:
            pytest.skip("attendance already exists for today for this worker")
        assert r.status_code == 200, r.text
        assert r.json()["verification_level"] == "flagged"

    def test_punch_in_duplicate_conflict(self):
        tok = _login(PH_ATT_DUP)["access_token"]
        payload = {"gps_lat": 19.0, "gps_lng": 74.7, "selfie_key": "s.jpg"}
        r1 = requests.post(f"{API}/attendance/punch-in", headers=_auth(tok), json=payload, timeout=15)
        # First may succeed (200) OR already be 409 from earlier run — either way second must be 409
        assert r1.status_code in (200, 409), r1.text
        r2 = requests.post(f"{API}/attendance/punch-in", headers=_auth(tok), json=payload, timeout=15)
        assert r2.status_code == 409, r2.text

    def test_flagged_listing_time_office_only(self, time_mgr, prod_worker):
        r = requests.get(f"{API}/attendance/flagged", headers=_auth(time_mgr["access_token"]), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        r = requests.get(f"{API}/attendance/flagged", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 403

    def test_dashboard_summary_cgm(self, cgm):
        r = requests.get(f"{API}/dashboard/attendance-summary", headers=_auth(cgm["access_token"]), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "departments" in body
        assert len(body["departments"]) >= 13


# ------------------------- shifts -------------------------

class TestShifts:
    def test_shifts_mine(self, prod_worker):
        r = requests.get(f"{API}/shifts/mine", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 8, f"expected 8 days, got {len(rows)}"
        assert all("date" in x and "shift_code" in x for x in rows)

    def test_swap_same_shift_and_cross_dept(self, prod_worker):
        # Same-shift PRODUCTION worker → 400 "same shift"
        # Find another PRODUCTION worker id
        r = requests.get(f"{API}/auth/me", headers=_auth(prod_worker["access_token"]), timeout=10)
        assert r.status_code == 200
        my_id = r.json()["id"]

        # Log in a different PRODUCTION worker to grab its id
        other = _login("+919700000079")
        other_id = other["employee"]["id"]
        # For an eligible-swap-eligible target: worker rows have shift_swap_eligible=true

        from datetime import date, timedelta
        swap_date = (date.today() + timedelta(days=2)).isoformat()

        payload = {"target_employee_id": other_id, "swap_date": swap_date, "reason": "test"}
        r = requests.post(f"{API}/shift-swaps", headers=_auth(prod_worker["access_token"]), json=payload, timeout=15)
        # Expect 400 due to same shift OR ineligibility
        assert r.status_code == 400, f"expected 400 same-shift, got {r.status_code}: {r.text}"

        # Cross-department: ENGINEERING worker (e.g. +919700000015 Staff — but staff have shift_swap_eligible=false).
        # Try a worker from ENGINEERING with eligible=true — pick a higher emp id likely a Worker.
        eng = _login("+919700000020")
        eng_id = eng["employee"]["id"]
        payload2 = {"target_employee_id": eng_id, "swap_date": swap_date, "reason": "test"}
        r = requests.post(f"{API}/shift-swaps", headers=_auth(prod_worker["access_token"]), json=payload2, timeout=15)
        # Either 400 for eligibility or 400 cross-dept — must be 400 regardless
        assert r.status_code == 400, r.text


# ------------------------- files -------------------------

class TestFiles:
    def test_upload_png_and_serve(self):
        # Minimal 1x1 PNG (valid header/data). It's fine even if not perfectly valid
        # because upload does no image validation.
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff"
            b"?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        files = {"file": ("test.png", io.BytesIO(png_bytes), "image/png")}
        r = requests.post(f"{API}/files/upload", files=files, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "key" in body and "url" in body
        r2 = requests.get(f"{BASE_URL}{body['url']}" if body["url"].startswith("/") else body["url"], timeout=10)
        assert r2.status_code == 200

    def test_upload_exe_rejected(self):
        files = {"file": ("bad.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
        r = requests.post(f"{API}/files/upload", files=files, timeout=10)
        assert r.status_code == 400, r.text


# ------------------------- admin -------------------------

class TestAdminSettings:
    def test_patch_settings_cgm_ok_worker_forbidden(self, cgm, prod_worker):
        r = requests.patch(
            f"{API}/admin/settings",
            headers=_auth(cgm["access_token"]),
            json={"radius_meters": 500},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["radius_meters"] == 500

        r = requests.patch(
            f"{API}/admin/settings",
            headers=_auth(prod_worker["access_token"]),
            json={"radius_meters": 500},
            timeout=10,
        )
        assert r.status_code == 403, r.text


# ------------------------- notifications -------------------------

class TestNotifications:
    def test_manager_notifications_after_incident(self, prod_mgr):
        r = requests.get(f"{API}/notifications/mine", headers=_auth(prod_mgr["access_token"]), timeout=10)
        assert r.status_code == 200
        body = r.json()
        items = body["items"]
        assert isinstance(items, list)
        # Should include incident_assigned rows given the earlier incident test
        assert any(n["type"] == "incident_assigned" for n in items), (
            f"expected incident_assigned notification, got types: {[n['type'] for n in items]}"
        )

        # mark one as read
        if items:
            nid = items[0]["id"]
            r = requests.post(f"{API}/notifications/{nid}/read", headers=_auth(prod_mgr["access_token"]), timeout=10)
            assert r.status_code == 200
            assert r.json()["is_read"] is True
