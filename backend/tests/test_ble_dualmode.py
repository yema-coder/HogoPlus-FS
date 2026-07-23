"""BLE dual-mode matching (MAC + iBeacon) + incident zone context tests."""
from tests.conftest import PHONES, login

INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}
IBEACON_UUID = "f7826da6-4fa2-4e98-8024-bc5b71e0893e"


# ---------------- attendance: verification via either identifier ----------------

async def test_punch_in_ibeacon_match_verified_plus(client):
    # registered iBeacon triple (UUID case-insensitive) → verified_plus
    headers = await login(client, PHONES["w_prod2"])
    r = await client.post(
        "/api/attendance/punch-in",
        json={**INSIDE, "selfie_key": "ib1.jpg",
              "ble_ibeacon_uuid": IBEACON_UUID.upper(), "ble_ibeacon_major": 1, "ble_ibeacon_minor": 1},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_level"] == "verified_plus"
    assert body["ble_zone"] == "Boiler House"
    assert body["ble_beacon_id"] == f"ibeacon:{IBEACON_UUID}:1:1"


async def test_punch_in_unregistered_ibeacon_ignored(client):
    # unknown minor → BLE ignored, GPS-only "verified"
    headers = await login(client, PHONES["w_eng"])
    r = await client.post(
        "/api/attendance/punch-in",
        json={**INSIDE, "selfie_key": "ib2.jpg",
              "ble_ibeacon_uuid": IBEACON_UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 999},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_level"] == "verified"
    assert body["ble_zone"] is None


async def test_beacon_registry_lists_both_modes(client):
    headers = await login(client, PHONES["w_att1"])
    r = await client.get("/api/attendance/beacon-registry", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "AA:BB:CC:DD:EE:01" in data["macs"]
    assert "AA:BB:CC:DD:EE:02" not in data["macs"]  # inactive excluded
    triples = {(b["uuid"], b["major"], b["minor"]) for b in data["ibeacons"]}
    assert (IBEACON_UUID, 1, 1) in triples


# ---------------- admin beacon CRUD validation ----------------

async def test_create_beacon_ibeacon_ok(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.post("/api/admin/beacons", json={
        "beacon_uuid": IBEACON_UUID, "major": 1, "minor": 2,
        "zone_label_en": "Pump Room", "zone_label_hi": "पंप रूम", "zone_label_mr": "पंप रूम",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "ibeacon"


async def test_create_beacon_missing_identifier_rejected(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.post("/api/admin/beacons", json={
        "zone_label_en": "Nowhere", "zone_label_hi": "x", "zone_label_mr": "x",
    }, headers=headers)
    assert r.status_code == 422, r.text


async def test_create_beacon_duplicate_ibeacon_rejected(client):
    headers = await login(client, PHONES["cgm"])
    payload = {
        "beacon_uuid": IBEACON_UUID, "major": 5, "minor": 50,
        "zone_label_en": "Dup", "zone_label_hi": "x", "zone_label_mr": "x",
    }
    r1 = await client.post("/api/admin/beacons", json=payload, headers=headers)
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/admin/beacons", json=payload, headers=headers)
    assert r2.status_code == 409, r2.text


async def test_bulk_import_registers_all(client):
    headers = await login(client, PHONES["cgm"])
    rows = [{"minor": 100 + i, "zone_name": f"Zone {i}"} for i in range(32)]
    r = await client.post("/api/admin/beacons/bulk", json={
        "beacon_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "major": 1,
        "department_code": "PRODUCTION", "rows": rows,
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"added": 32, "skipped": 0, "total": 32}
    # re-import same set → all skipped
    r2 = await client.post("/api/admin/beacons/bulk", json={
        "beacon_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "major": 1,
        "rows": rows,
    }, headers=headers)
    assert r2.json()["skipped"] == 32


# ---------------- incident zone context ----------------

async def test_incident_with_matched_beacon_stores_zone(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/incidents", json={
        "category": "safety", "department_code": "PRODUCTION", "photo_key": "inc.jpg",
        "description": "beacon context",
        "ble_ibeacon_uuid": IBEACON_UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 1,
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ble_zone"] == "Boiler House"


async def test_incident_without_beacon_null_zone(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/incidents", json={
        "category": "safety", "department_code": "PRODUCTION", "photo_key": "inc2.jpg",
        "description": "no beacon",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ble_zone"] is None


async def test_incident_unregistered_beacon_ignored(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/incidents", json={
        "category": "safety", "department_code": "PRODUCTION", "photo_key": "inc3.jpg",
        "ble_beacon_id": "99:99:99:99:99:99",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ble_zone"] is None
