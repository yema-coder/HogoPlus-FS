"""v1.0.17 iter 20 spot-check: POST /api/attendance/{id}/attach-beacon.

Login demo worker +919000000021, punch-in without beacon (GPS only), then
attach-beacon and expect verification_level -> verified_plus, ble_zone -> Boiler.
"""
import os
import requests

BASE = "https://hogo-backend-phase1.preview.emergentagent.com"
PHONE = "+919000000021"
OTP = "123456"
UUID = "01122334-4556-6778-899A-ABBCCDDEEFF0"


def _auth():
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": PHONE}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": PHONE, "otp": OTP}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("access_token") or body.get("access") or body.get("token")
    assert tok, body
    return tok


def test_attach_beacon_upgrades_to_verified_plus():
    tok = _auth()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    # Punch-in with GPS only, no beacon
    r = requests.post(
        f"{BASE}/api/attendance/punch-in",
        headers=h,
        json={"selfie_key": "x.jpg", "gps_lat": 19.3134, "gps_lng": 74.7093},
        timeout=20,
    )
    # Could 409 if already punched today - handle that by fetching existing row
    if r.status_code == 409:
        # already punched today: attempt to find it via GET /api/attendance/mine (if exists)
        # Fall back: skip test since we can't cleanly re-punch demo worker in this window.
        import pytest
        pytest.skip(f"Already punched today: {r.text}")
    assert r.status_code == 200, r.text
    rec = r.json()
    att_id = rec.get("id")
    assert att_id, rec
    print(f"Punched: id={att_id} level={rec.get('verification_level')} zone={rec.get('ble_zone')}")

    # Attach beacon
    r2 = requests.post(
        f"{BASE}/api/attendance/{att_id}/attach-beacon",
        headers=h,
        json={"ble_ibeacon_uuid": UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 22},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    print(f"Attach response: {body}")
    assert body.get("ble_zone") == "Boiler", body
    assert body.get("verification_level") == "verified_plus", body
