"""v1.0.17 speed pack: POST /attendance/{id}/attach-beacon — late-arriving beacon
match upgrades the row (beacon wins over location outcomes, never over face flags)."""
import uuid as uuidlib

import pytest_asyncio
from sqlalchemy import delete, select

from app.models import Attendance, Employee
from tests.conftest import PHONES, login

IB = {"ble_ibeacon_uuid": "f7826da6-4fa2-4e98-8024-bc5b71e0893e", "ble_ibeacon_major": 1, "ble_ibeacon_minor": 1}
INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}
WORKER = PHONES["w_att4"]


async def _wipe(db_session):
    emp_id = (
        await db_session.execute(select(Employee.id).where(Employee.phone == WORKER))
    ).scalar_one()
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == emp_id))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean(db_session):
    await _wipe(db_session)
    yield
    await _wipe(db_session)


async def _punch(client, payload):
    headers = await login(client, WORKER)
    r = await client.post(
        "/api/attendance/punch-in", json={"selfie_key": "ab.jpg", **payload}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json(), headers


async def test_attach_upgrades_verified_to_verified_plus(client):
    rec, headers = await _punch(client, INSIDE)  # no beacon → verified (inside geofence)
    assert rec["verification_level"] == "verified" and rec["ble_zone"] is None
    r = await client.post(f"/api/attendance/{rec['id']}/attach-beacon", json=IB, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ble_zone"] == "Boiler House"
    assert out["verification_level"] == "verified_plus"
    assert out["flagged_reason"] is None


async def test_attach_upgrades_location_flagged(client):
    rec, headers = await _punch(client, {})  # no gps, no beacon → flagged gps_missing
    assert rec["verification_level"] == "flagged"
    r = await client.post(f"/api/attendance/{rec['id']}/attach-beacon", json=IB, headers=headers)
    assert r.status_code == 200
    assert r.json()["verification_level"] == "verified_plus"


async def test_attach_never_touches_face_flags(client, db_session):
    rec, headers = await _punch(client, INSIDE)
    row = (
        await db_session.execute(select(Attendance).where(Attendance.id == uuidlib.UUID(rec["id"])))
    ).scalar_one()
    row.verification_level = "flagged"
    row.flagged_reason = "face_mismatch(score=41.2)"
    await db_session.commit()
    r = await client.post(f"/api/attendance/{rec['id']}/attach-beacon", json=IB, headers=headers)
    assert r.status_code == 200
    out = r.json()
    assert out["ble_zone"] == "Boiler House"  # zone evidence still attached
    assert out["verification_level"] == "flagged"  # face flag preserved
    assert out["flagged_reason"].startswith("face_mismatch")


async def test_attach_idempotent_and_guards(client, db_session):
    rec, headers = await _punch(client, {**INSIDE, **IB})  # already has beacon
    assert rec["verification_level"] == "verified_plus"
    r = await client.post(
        f"/api/attendance/{rec['id']}/attach-beacon",
        json={**IB, "ble_ibeacon_minor": 99},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["ble_beacon_id"] == rec["ble_beacon_id"]  # unchanged

    # unregistered beacon on a fresh row → 404
    await _wipe(db_session)
    rec2, headers = await _punch(client, INSIDE)
    r2 = await client.post(
        f"/api/attendance/{rec2['id']}/attach-beacon",
        json={**IB, "ble_ibeacon_minor": 999},
        headers=headers,
    )
    assert r2.status_code == 404

    # someone else's row → 404
    other = await login(client, PHONES["w_prod1"])
    r3 = await client.post(f"/api/attendance/{rec2['id']}/attach-beacon", json=IB, headers=other)
    assert r3.status_code == 404
