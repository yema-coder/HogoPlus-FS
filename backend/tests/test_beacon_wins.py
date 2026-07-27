"""BEACON WINS ladder matrix (launch order 2026-07-27).

A matched REGISTERED beacon is physical proof of presence → verified_plus even when
GPS is outside the geofence or missing. Geofence/GPS flagging applies only when NO
registered beacon matched. Full matrix, each case cleans up its own attendance row
so the shared session-scoped seed stays reusable.
"""
import pytest_asyncio
from sqlalchemy import delete, select

from app.models import Attendance, Employee
from tests.conftest import PHONES, login

INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}          # == test geofence center (500m radius)
OUTSIDE = {"gps_lat": 19.3135, "gps_lng": 74.7094}          # ~34.8 km away (real factory cluster)
IBEACON_UUID = "f7826da6-4fa2-4e98-8024-bc5b71e0893e"      # registered → Boiler House (major 1, minor 1)
REGISTERED_IB = {"ble_ibeacon_uuid": IBEACON_UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 1}
UNREGISTERED_IB = {"ble_ibeacon_uuid": IBEACON_UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 999}
REGISTERED_MAC = {"ble_beacon_id": "AA:BB:CC:DD:EE:01"}    # registered active MAC beacon

WORKER = PHONES["w_att5"]


@pytest_asyncio.fixture(autouse=True)
async def _clean_worker_attendance(db_session):
    """Each matrix case punches the same worker — wipe the row before & after."""
    emp_id = (
        await db_session.execute(select(Employee.id).where(Employee.phone == WORKER))
    ).scalar_one()
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == emp_id))
    await db_session.commit()
    yield
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == emp_id))
    await db_session.commit()


async def _punch(client, payload):
    headers = await login(client, WORKER)
    r = await client.post(
        "/api/attendance/punch-in",
        json={"selfie_key": "ladder.jpg", **payload},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- BEACON MATCHED: wins over any GPS state ----------------

async def test_beacon_inside_verified_plus(client):
    body = await _punch(client, {**INSIDE, **REGISTERED_IB})
    assert body["verification_level"] == "verified_plus"
    assert body["flagged_reason"] is None
    assert body["ble_zone"] == "Boiler House"


async def test_beacon_outside_geofence_verified_plus(client):
    """THE FIX: beacon matched + GPS outside → verified_plus (was flagged before)."""
    body = await _punch(client, {**OUTSIDE, **REGISTERED_IB})
    assert body["verification_level"] == "verified_plus"
    assert body["flagged_reason"] is None
    assert body["ble_zone"] == "Boiler House"
    assert body["gps_verified"] is False  # audit truth preserved: GPS was NOT inside


async def test_beacon_gps_missing_verified_plus(client):
    """THE FIX: beacon matched + no GPS at all → verified_plus (was flagged gps_missing)."""
    body = await _punch(client, REGISTERED_IB)
    assert body["verification_level"] == "verified_plus"
    assert body["flagged_reason"] is None
    assert body["ble_zone"] == "Boiler House"
    assert body["gps_verified"] is False


async def test_beacon_mac_mode_outside_verified_plus(client):
    """Dual-mode parity: MAC-registered beacon also wins outside the geofence."""
    body = await _punch(client, {**OUTSIDE, **REGISTERED_MAC})
    assert body["verification_level"] == "verified_plus"
    assert body["flagged_reason"] is None
    assert body["ble_beacon_id"] == "AA:BB:CC:DD:EE:01"


# ---------------- NO BEACON MATCHED: geofence ladder unchanged ----------------

async def test_no_beacon_inside_verified(client):
    body = await _punch(client, INSIDE)
    assert body["verification_level"] == "verified"
    assert body["flagged_reason"] is None
    assert body["ble_zone"] is None


async def test_no_beacon_outside_flagged(client):
    body = await _punch(client, OUTSIDE)
    assert body["verification_level"] == "flagged"
    assert body["flagged_reason"].startswith("outside_geofence(")
    assert body["gps_verified"] is False


async def test_no_beacon_gps_missing_flagged(client):
    body = await _punch(client, {})
    assert body["verification_level"] == "flagged"
    assert body["flagged_reason"] == "gps_missing"


async def test_unregistered_beacon_outside_still_flagged(client):
    """An UNREGISTERED beacon must NOT win — only registry rows prove presence."""
    body = await _punch(client, {**OUTSIDE, **UNREGISTERED_IB})
    assert body["verification_level"] == "flagged"
    assert body["flagged_reason"].startswith("outside_geofence(")
    assert body["ble_zone"] is None
