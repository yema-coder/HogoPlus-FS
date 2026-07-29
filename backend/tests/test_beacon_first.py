"""BEACON-FIRST POLICY matrix (Task B) — settings.beacon_first_mode, ships OFF.

Flag OFF  -> byte-identical to the launch BEACON-WINS ladder (mirrors test_beacon_wins).
Flag ON   -> beacon zone is the PRIMARY identity; GPS is stored evidence only:
             registered beacon match = verified_plus; NO beacon = punch ACCEPTED but
             flagged (no_beacon_gps_only / no_beacon_no_gps). Geofence never gates.
Incidents are NEVER blocked or flagged for a missing beacon in either mode.
"""
import uuid as uuidlib

import pytest_asyncio
from sqlalchemy import delete, select

from app.models import Attendance, Employee, FactorySettings
from tests.conftest import PHONES, login

INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}          # == test geofence center (500m radius)
OUTSIDE = {"gps_lat": 19.3135, "gps_lng": 74.7094}          # ~34.8 km away
IBEACON_UUID = "f7826da6-4fa2-4e98-8024-bc5b71e0893e"      # registered → Boiler House (major 1, minor 1)
REGISTERED_IB = {"ble_ibeacon_uuid": IBEACON_UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 1}

WORKER = PHONES["w_att4"]


async def _set_flag(db_session, value: bool) -> None:
    s = (await db_session.execute(select(FactorySettings))).scalars().first()
    s.beacon_first_mode = value
    await db_session.commit()


async def _wipe(db_session) -> None:
    emp_id = (
        await db_session.execute(select(Employee.id).where(Employee.phone == WORKER))
    ).scalar_one()
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == emp_id))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _reset(db_session):
    await _wipe(db_session)
    await _set_flag(db_session, False)
    yield
    await _wipe(db_session)
    await _set_flag(db_session, False)


async def _punch(client, db_session, payload):
    await _wipe(db_session)  # same worker punches once per case
    headers = await login(client, WORKER)
    r = await client.post(
        "/api/attendance/punch-in", json={"selfie_key": "bf.jpg", **payload}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


# (payload, expected with flag OFF, expected with flag ON) — reason "outside_geofence(" is a prefix
MATRIX = [
    ({**INSIDE, **REGISTERED_IB}, ("verified_plus", None), ("verified_plus", None)),
    ({**OUTSIDE, **REGISTERED_IB}, ("verified_plus", None), ("verified_plus", None)),
    ({**REGISTERED_IB}, ("verified_plus", None), ("verified_plus", None)),
    ({**INSIDE}, ("verified", None), ("flagged", "no_beacon_gps_only")),
    ({**OUTSIDE}, ("flagged", "outside_geofence("), ("flagged", "no_beacon_gps_only")),
    ({}, ("flagged", "gps_missing"), ("flagged", "no_beacon_no_gps")),
]


def _check(body, expected):
    level, reason = expected
    assert body["verification_level"] == level, body
    if reason is None:
        assert body["flagged_reason"] is None, body
    else:
        assert body["flagged_reason"].startswith(reason), body


async def test_matrix_flag_off_byte_identical(client, db_session):
    await _set_flag(db_session, False)
    for payload, off_expected, _ in MATRIX:
        body = await _punch(client, db_session, payload)
        _check(body, off_expected)
        # GPS evidence always stored regardless of outcome
        if "gps_lat" in payload:
            assert body["gps_lat"] == payload["gps_lat"]


async def test_matrix_flag_on_beacon_first(client, db_session):
    await _set_flag(db_session, True)
    for payload, _, on_expected in MATRIX:
        body = await _punch(client, db_session, payload)
        _check(body, on_expected)
        if REGISTERED_IB["ble_ibeacon_uuid"] == payload.get("ble_ibeacon_uuid"):
            assert body["ble_zone"] == "Boiler House"
        if "gps_lat" in payload:
            assert body["gps_lat"] == payload["gps_lat"]  # secondary evidence kept
    # geofence truth still recorded as evidence even though it no longer gates
    inside_row = await _punch(client, db_session, {**INSIDE})
    assert inside_row["gps_verified"] is True
    outside_row = await _punch(client, db_session, {**OUTSIDE})
    assert outside_row["gps_verified"] is False


async def test_flag_on_no_beacon_punch_still_accepted(client, db_session):
    """Explicit acceptance check: flag ON + zero beacon = 200, row persisted, flagged."""
    await _set_flag(db_session, True)
    body = await _punch(client, db_session, {**INSIDE})
    assert body["verification_level"] == "flagged"
    assert body["flagged_reason"] == "no_beacon_gps_only"
    row = (
        await db_session.execute(select(Attendance).where(Attendance.id == uuidlib.UUID(body["id"])))
    ).scalar_one()
    assert row.ble_zone is None and row.gps_lat is not None


async def test_flag_on_incidents_never_blocked(client, db_session):
    await _set_flag(db_session, True)
    headers = await login(client, PHONES["w_prod1"])
    # no beacon → submits normally, no flag, zone empty
    r = await client.post("/api/incidents", json={
        "category": "safety", "department_code": "PRODUCTION", "photo_key": "bf-inc1.jpg",
        "description": "beacon-first: no beacon",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ble_zone"] is None
    assert r.json()["status"] == "submitted"
    # registered beacon → zone attached as primary location
    r2 = await client.post("/api/incidents", json={
        "category": "safety", "department_code": "PRODUCTION", "photo_key": "bf-inc2.jpg",
        "description": "beacon-first: with beacon",
        **REGISTERED_IB,
    }, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["ble_zone"] == "Boiler House"


async def test_settings_flag_roundtrip(client, db_session):
    """PATCH /admin/settings flips the flag; GET reflects it; default is OFF."""
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/settings", headers=headers)
    assert r.status_code == 200
    assert r.json()["beacon_first_mode"] is False
    r = await client.patch(
        "/api/admin/settings", json={"beacon_first_mode": True}, headers=headers
    )
    assert r.status_code == 200 and r.json()["beacon_first_mode"] is True
    r = await client.patch(
        "/api/admin/settings", json={"beacon_first_mode": False}, headers=headers
    )
    assert r.status_code == 200 and r.json()["beacon_first_mode"] is False


async def test_beacon_registry_returns_zone_labels(client):
    """v1.0.15: registry entries carry trilingual zone labels for the live capture
    chip; legacy keys (macs / ibeacons uuid+major+minor) unchanged for old builds."""
    headers = await login(client, WORKER)
    r = await client.get("/api/attendance/beacon-registry", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"macs", "ibeacons", "macs_detail"}
    entry = next(i for i in data["ibeacons"] if i["minor"] == 1 and i["major"] == 1)
    assert entry["zone_en"] == "Boiler House"
    assert entry["zone_hi"] and entry["zone_mr"]
    mac_entry = next(m for m in data["macs_detail"] if m["mac"] == "AA:BB:CC:DD:EE:01")
    assert mac_entry["zone_en"]
    assert "AA:BB:CC:DD:EE:01" in data["macs"]  # legacy list intact
