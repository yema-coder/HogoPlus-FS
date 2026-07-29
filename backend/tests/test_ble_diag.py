"""v1.0.16 BLE field instrumentation: POST /attendance/ble-diag stores an on-device
diagnostic report as an audit event; GET /admin/ble-diag (CGM/MD) reads it back."""
from tests.conftest import PHONES, login

REPORT = {
    "app_version": "1.0.16",
    "platform": "android 34",
    "permissions": {"scan": True, "fineLocation": False},
    "scan": {"devicesSeen": 3, "matchedCount": 0, "devices": [{"id": "AA:BB", "verdict": "uuid_mismatch"}]},
}


async def test_ble_diag_roundtrip(client):
    worker = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/attendance/ble-diag", json={"report": REPORT}, headers=worker)
    assert r.status_code == 200, r.text
    assert r.json() == {"stored": True}

    cgm = await login(client, PHONES["cgm"])
    r2 = await client.get("/api/admin/ble-diag", headers=cgm)
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) >= 1
    latest = items[0]
    assert latest["report"]["scan"]["matchedCount"] == 0
    assert latest["report"]["permissions"]["fineLocation"] is False
    assert latest["emp_id"] is not None


async def test_ble_diag_worker_cannot_read(client):
    worker = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/admin/ble-diag", headers=worker)
    assert r.status_code == 403


async def test_ble_diag_oversized_rejected(client):
    worker = await login(client, PHONES["w_prod1"])
    huge = {"blob": "x" * 200_000}
    r = await client.post("/api/attendance/ble-diag", json={"report": huge}, headers=worker)
    assert r.status_code == 413
