"""Prompt 8: Demo OTP whitelist + BLE beacon MAC CRUD live tests against production API.

Runs against EXPO_PUBLIC_BACKEND_URL (Neon prod DB). All beacons created are cleaned up
in the class teardown fixture. NEVER modifies employees / settings / SOP docs.
"""
import os
import time
import uuid

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

CGM_PHONE = "+918483029039"
WORKER_PHONE = "+917972540971"
NON_WL_PHONE = "+918308829567"  # TIME_OFFICE Manager Kale Shailendra
DEMO_OTP = "123456"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def cgm_token(s):
    r = s.post(f"{API}/auth/verify-otp", json={"phone": CGM_PHONE, "otp": DEMO_OTP}, timeout=20)
    assert r.status_code == 200, f"CGM login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


# --- Prompt 8: whitelist enforcement ---

class TestWhitelist:
    def test_cgm_whitelist_ok(self, s):
        r = s.post(f"{API}/auth/verify-otp", json={"phone": CGM_PHONE, "otp": DEMO_OTP}, timeout=20)
        assert r.status_code == 200
        j = r.json()
        assert "access_token" in j and "refresh_token" in j

    def test_worker_whitelist_ok(self, s):
        r = s.post(f"{API}/auth/verify-otp", json={"phone": WORKER_PHONE, "otp": DEMO_OTP}, timeout=20)
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_non_whitelisted_seeded_phone_rejects_demo_otp(self, s):
        # Single attempt only — the account has a 5-wrong/30-min lockout.
        r = s.post(f"{API}/auth/verify-otp", json={"phone": NON_WL_PHONE, "otp": DEMO_OTP}, timeout=20)
        assert r.status_code == 401, f"Expected 401 got {r.status_code}: {r.text}"


# --- beacon-macs endpoint ---

class TestBeaconMacsEndpoint:
    def test_no_token_401(self, s):
        r = requests.get(f"{API}/attendance/beacon-macs", timeout=15)
        assert r.status_code == 401

    def test_with_cgm_token_200(self, s, cgm_token):
        r = requests.get(f"{API}/attendance/beacon-macs",
                         headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "macs" in body and isinstance(body["macs"], list)


# --- beacon CRUD (with cleanup) ---

@pytest.fixture(scope="class")
def created_beacons():
    """Track beacons for teardown cleanup."""
    ids: list[str] = []
    yield ids
    if ids:
        # Cleanup at class teardown — best-effort using fresh CGM token
        try:
            r = requests.post(f"{API}/auth/verify-otp",
                              json={"phone": CGM_PHONE, "otp": DEMO_OTP}, timeout=20)
            tok = r.json().get("access_token")
            if tok:
                for bid in ids:
                    requests.delete(f"{API}/admin/beacons/{bid}",
                                    headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        except Exception as e:
            print(f"CLEANUP WARNING: {e}")


class TestBeaconCRUD:
    # Random MAC per test-run to avoid 409 duplicates on repeated runs
    MAC_LOWER = f"e1:e2:e3:e4:e5:{uuid.uuid4().hex[:2]}"
    MAC_UPPER = MAC_LOWER.upper()

    def test_01_create_beacon_normalizes_mac(self, cgm_token, created_beacons):
        body = {
            "mac_address": self.MAC_LOWER,
            "zone_label_en": "TEST_QA Zone",
            "zone_label_hi": "TEST_QA क्षेत्र",
            "zone_label_mr": "TEST_QA क्षेत्र",
        }
        r = requests.post(f"{API}/admin/beacons", json=body,
                          headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["mac_address"] == self.MAC_UPPER
        assert j["is_active"] is True
        created_beacons.append(j["id"])

    def test_02_duplicate_mac_409(self, cgm_token, created_beacons):
        body = {
            "mac_address": self.MAC_UPPER,
            "zone_label_en": "TEST_QA Zone dup",
            "zone_label_hi": "x", "zone_label_mr": "x",
        }
        r = requests.post(f"{API}/admin/beacons", json=body,
                          headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"

    def test_03_invalid_mac_422(self, cgm_token):
        body = {
            "mac_address": "garbage",
            "zone_label_en": "x", "zone_label_hi": "x", "zone_label_mr": "x",
        }
        r = requests.post(f"{API}/admin/beacons", json=body,
                          headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    def test_04_macs_endpoint_lists_active_mac(self, cgm_token, created_beacons):
        assert created_beacons, "beacon must exist from test_01"
        r = requests.get(f"{API}/attendance/beacon-macs",
                         headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 200
        macs = r.json()["macs"]
        assert self.MAC_UPPER in macs

    def test_05_patch_inactive_removes_from_macs(self, cgm_token, created_beacons):
        bid = created_beacons[0]
        r = requests.patch(f"{API}/admin/beacons/{bid}", json={"is_active": False},
                           headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        # verify beacon-macs no longer lists it
        r2 = requests.get(f"{API}/attendance/beacon-macs",
                          headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        macs = r2.json()["macs"]
        assert self.MAC_UPPER not in macs

    def test_06_delete_beacon(self, cgm_token, created_beacons):
        bid = created_beacons[0]
        r = requests.delete(f"{API}/admin/beacons/{bid}",
                            headers={"Authorization": f"Bearer {cgm_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("deleted") is True
        created_beacons.remove(bid)
