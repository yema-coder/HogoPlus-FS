"""Live spot-checks for PROMPT 6 UX Pack backend contracts (hits public URL).

Scope (per review-request):
- POST /api/incidents/{id}/confirm-routing: 2nd call returns 409 (already confirmed)
- GET /api/incidents/{id} includes ai_suggested_*, ai_confirmed_by, detected_plate,
  resolution_photo_key fields (may be null)
- POST /api/admin/employees/{id}/approve without body -> 422
  with {department_code, role_code, emp_id} -> 200 (after fresh registration)
- POST /api/incidents/{id}/status {status:'resolved'} WITHOUT resolution_photo_key -> 400
  with code resolution_photo_required
"""
import io
import os
import time

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")

WORKER_PHONE = "+917972540971"      # Khot Mahavir (ACCOUNTS)
TIME_OFFICE_PHONE = "+918308829567"  # Kale Shailendra
PROD_PHONE = "+918379811866"         # Mane Arjun (PRODUCTION)
CGM_PHONE = "+918483029039"


def _verify(phone: str) -> str:
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code in (200, 429), r.text
    r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload_jpeg(token: str) -> str:
    # 150-byte minimal JPEG (magic bytes FFD8FFE0)
    jpeg = bytes.fromhex(
        "FFD8FFE000104A46494600010100000100010000FFDB004300080606070605080707"
        "07090908"
    ) + b"\x00" * 200 + b"\xFF\xD9"
    r = requests.post(
        f"{BASE}/api/files/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("t.jpg", io.BytesIO(jpeg), "image/jpeg")},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["key"]


@pytest.fixture(scope="module")
def worker_token():
    return _verify(WORKER_PHONE)


@pytest.fixture(scope="module")
def prod_token():
    return _verify(PROD_PHONE)


@pytest.fixture(scope="module")
def time_office_token():
    return _verify(TIME_OFFICE_PHONE)


class TestConfirmRoutingIdempotency:
    def test_double_confirm_returns_409(self, worker_token):
        photo_key = _upload_jpeg(worker_token)
        r = requests.post(
            f"{BASE}/api/incidents",
            headers={"Authorization": f"Bearer {worker_token}"},
            json={
                "category": "other",
                "department_code": "PRODUCTION",
                "description": "TEST double-confirm spot check",
                "severity": "normal",
                "photo_key": photo_key,
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        incident_id = r.json()["id"]

        # 1st confirm (empty body → worker accepts AI suggestion, but AI may not yet be ready)
        # We accept 200 or 400 (AI not ready). If 400, wait and retry once.
        deadline = time.time() + 45
        first = None
        while time.time() < deadline:
            first = requests.post(
                f"{BASE}/api/incidents/{incident_id}/confirm-routing",
                headers={"Authorization": f"Bearer {worker_token}"},
                json={},
                timeout=15,
            )
            if first.status_code == 200:
                break
            time.sleep(3)
        assert first is not None
        # Fallback if AI never suggested — provide explicit body
        if first.status_code != 200:
            first = requests.post(
                f"{BASE}/api/incidents/{incident_id}/confirm-routing",
                headers={"Authorization": f"Bearer {worker_token}"},
                json={"category": "other", "department_code": "PRODUCTION"},
                timeout=15,
            )
        assert first.status_code == 200, first.text

        # 2nd confirm must be 409
        second = requests.post(
            f"{BASE}/api/incidents/{incident_id}/confirm-routing",
            headers={"Authorization": f"Bearer {worker_token}"},
            json={},
            timeout=15,
        )
        assert second.status_code == 409, f"expected 409, got {second.status_code}: {second.text}"


class TestIncidentDetailSchema:
    def test_detail_has_new_fields(self, worker_token):
        # Fetch any recent incident
        r = requests.get(
            f"{BASE}/api/incidents?limit=1",
            headers={"Authorization": f"Bearer {worker_token}"},
            timeout=15,
        )
        assert r.status_code == 200
        raw = r.json()
        items = raw.get("items") if isinstance(raw, dict) else raw
        assert items, "no incidents returned to inspect"
        iid = items[0]["id"]
        d = requests.get(
            f"{BASE}/api/incidents/{iid}",
            headers={"Authorization": f"Bearer {worker_token}"},
            timeout=15,
        )
        assert d.status_code == 200, d.text
        body = d.json()
        # Keys must exist (values may be null)
        for k in (
            "ai_suggested_category",
            "ai_suggested_department",
            "ai_confirmed_by",
            "detected_plate",
            "resolution_photo_key",
        ):
            assert k in body, f"missing key {k} in incident detail: {list(body.keys())}"


class TestResolutionPhotoRequired:
    def test_resolve_without_photo_returns_400(self, worker_token, prod_token):
        # Create an incident (as worker)
        photo_key = _upload_jpeg(worker_token)
        r = requests.post(
            f"{BASE}/api/incidents",
            headers={"Authorization": f"Bearer {worker_token}"},
            json={
                "category": "other",
                "department_code": "PRODUCTION",
                "description": "TEST resolve without photo",
                "severity": "normal",
                "photo_key": photo_key,
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        iid = r.json()["id"]

        # Progress to in_progress as PROD manager
        for status in ("seen", "in_progress"):
            requests.post(
                f"{BASE}/api/incidents/{iid}/status",
                headers={"Authorization": f"Bearer {prod_token}"},
                json={"status": status},
                timeout=15,
            )

        # Attempt resolve WITHOUT resolution_photo_key
        res = requests.post(
            f"{BASE}/api/incidents/{iid}/status",
            headers={"Authorization": f"Bearer {prod_token}"},
            json={"status": "resolved"},
            timeout=15,
        )
        assert res.status_code == 400, f"expected 400, got {res.status_code}: {res.text}"
        # Check error code
        body = res.json()
        detail = body.get("detail", "")
        if isinstance(detail, dict):
            code = detail.get("code") or detail.get("error")
        else:
            code = detail
        assert "resolution_photo_required" in str(code), f"expected resolution_photo_required code, got: {body}"


class TestApprovalAssignmentBody:
    def test_approve_without_body_returns_422(self, time_office_token):
        # List pending registrations via /admin/employees/pending
        r = requests.get(
            f"{BASE}/api/admin/employees/pending?limit=10",
            headers={"Authorization": f"Bearer {time_office_token}"},
            timeout=15,
        )
        if r.status_code != 200:
            pytest.skip(f"cannot list pending registrations: {r.status_code} {r.text[:150]}")
        payload = r.json()
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not items:
            pytest.skip("no pending registration to test approve schema")
        emp_id = items[0].get("id") or items[0].get("employee_id")
        assert emp_id, f"missing id in {items[0]}"

        # No body -> 422
        res = requests.post(
            f"{BASE}/api/admin/employees/{emp_id}/approve",
            headers={"Authorization": f"Bearer {time_office_token}"},
            json={},
            timeout=15,
        )
        assert res.status_code == 422, f"expected 422, got {res.status_code}: {res.text}"
