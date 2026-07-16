from datetime import datetime, time
from zoneinfo import ZoneInfo

from tests.conftest import PHONES, login

IST = ZoneInfo("Asia/Kolkata")

INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}
OUTSIDE = {"gps_lat": 19.1000, "gps_lng": 74.8000}  # ~15 km away


async def test_punch_in_verified_plus(client):
    # registered vendor beacon MAC (case-insensitive) → verified_plus, backend resolves zone
    headers = await login(client, PHONES["w_att1"])
    r = await client.post(
        "/api/attendance/punch-in",
        json={**INSIDE, "selfie_key": "s1.jpg", "ble_beacon_id": "aa:bb:cc:dd:ee:01"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_level"] == "verified_plus"
    assert body["ble_beacon_id"] == "AA:BB:CC:DD:EE:01"
    assert body["ble_zone"] == "Mill Gate"
    assert body["gps_verified"] is True
    assert body["shift_code"] == "GEN"


async def test_punch_in_unregistered_mac_ignored(client):
    # unregistered MAC → BLE ignored, falls back to GPS-only "verified"
    headers = await login(client, PHONES["w_att5"])
    r = await client.post(
        "/api/attendance/punch-in",
        json={**INSIDE, "selfie_key": "s5.jpg", "ble_beacon_id": "11:22:33:44:55:66"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_level"] == "verified"
    assert body["ble_zone"] is None


async def test_beacon_macs_lists_active_registered_macs(client):
    headers = await login(client, PHONES["w_att1"])
    r = await client.get("/api/attendance/beacon-macs", headers=headers)
    assert r.status_code == 200
    macs = r.json()["macs"]
    assert "AA:BB:CC:DD:EE:01" in macs
    assert "AA:BB:CC:DD:EE:02" not in macs  # inactive beacon excluded


async def test_punch_in_verified_no_beacon(client):
    headers = await login(client, PHONES["w_att2"])
    r = await client.post(
        "/api/attendance/punch-in", json={**INSIDE, "selfie_key": "s2.jpg"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["verification_level"] == "verified"


async def test_punch_in_flagged_outside_geofence(client):
    headers = await login(client, PHONES["w_att3"])
    r = await client.post(
        "/api/attendance/punch-in", json={**OUTSIDE, "selfie_key": "s3.jpg"}, headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verification_level"] == "flagged"
    assert "outside_geofence" in body["flagged_reason"]
    assert body["gps_verified"] is False


async def test_duplicate_punch_in_409(client):
    headers = await login(client, PHONES["w_att1"])
    r = await client.post(
        "/api/attendance/punch-in", json={**INSIDE, "selfie_key": "dup.jpg"}, headers=headers
    )
    assert r.status_code == 409


async def test_punch_out(client):
    headers = await login(client, PHONES["w_att2"])
    r = await client.post("/api/attendance/punch-out", headers=headers)
    assert r.status_code == 200
    assert r.json()["punch_out_at"] is not None


async def test_late_computation(client):
    headers = await login(client, PHONES["w_att4"])
    now = datetime.now(IST)
    expected_late = now.time() > time(9, 15)  # GEN shift starts 09:00, 15-min grace
    r = await client.post(
        "/api/attendance/punch-in", json={**INSIDE, "selfie_key": "s4.jpg"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["is_late"] == expected_late


async def test_selfie_mandatory(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/attendance/punch-in", json={**INSIDE, "selfie_key": ""}, headers=headers)
    assert r.status_code == 422


async def test_flagged_list_and_approval(client, db_session):
    # Time Office manager sees flagged entries and approves them
    headers = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/attendance/flagged", headers=headers)
    assert r.status_code == 200
    flagged = r.json()
    assert len(flagged) >= 1
    target = flagged[0]
    r2 = await client.post(f"/api/attendance/{target['id']}/approve", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["approved_by"] is not None
    # worker cannot access flagged list
    w_headers = await login(client, PHONES["w_att3"])
    r3 = await client.get("/api/attendance/flagged", headers=w_headers)
    assert r3.status_code == 403


async def test_attendance_mine(client):
    headers = await login(client, PHONES["w_att1"])
    r = await client.get("/api/attendance/mine", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_worker_cannot_view_department_attendance(client):
    headers = await login(client, PHONES["w_att1"])
    r = await client.get("/api/attendance/department/PRODUCTION", headers=headers)
    assert r.status_code == 403


async def test_attendance_summary(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/dashboard/attendance-summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    prod = next(d for d in body["departments"] if d["department_code"] == "PRODUCTION")
    assert prod["present"] >= 3
    assert prod["flagged"] >= 1
