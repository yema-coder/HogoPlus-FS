"""Per-department verification ladder + GPS path + auto punch-out source (2026-06).

The test database is shared across the whole session, so these tests (a) toggle only
config they restore afterwards and (b) DELETE the attendance rows they create in teardown,
so the workers they punch stay free for the other suites that reuse them.
"""
from sqlalchemy import delete, select

from app.models import Attendance, Department, FactorySettings
from tests.conftest import PHONES, employee_id_by_phone, login

INSIDE = {"gps_lat": 19.0000, "gps_lng": 74.7000}
OUTSIDE = {"gps_lat": 19.1000, "gps_lng": 74.8000}  # ~15 km away


async def _set_dept_field(db_session, dept_code: str, field: bool):
    d = (await db_session.execute(select(Department).where(Department.code == dept_code))).scalar_one()
    d.geofence_exempt = field
    d.beacon_exempt = field
    await db_session.commit()


async def _set_settings(db_session, **kw):
    s = (await db_session.execute(select(FactorySettings).limit(1))).scalar_one()
    for k, v in kw.items():
        setattr(s, k, v)
    await db_session.commit()


async def _del_attendance(db_session, phone: str):
    emp_id = await employee_id_by_phone(db_session, phone)
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == emp_id))
    await db_session.commit()


async def test_field_department_outside_geofence_is_verified(client, db_session):
    # SECURITY marked FIELD → staff punch 15 km away → VERIFIED (field), not flagged.
    await _set_dept_field(db_session, "SECURITY", True)
    try:
        headers = await login(client, PHONES["w_sec"])
        r = await client.post(
            "/api/attendance/punch-in",
            json={**OUTSIDE, "gps_accuracy": 30, "selfie_key": "f1.jpg"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["verification_level"] == "verified"
        assert b["verification_path"] == "field"
        assert b["gps_accuracy"] == 30
    finally:
        await _set_dept_field(db_session, "SECURITY", False)
        await _del_attendance(db_session, PHONES["w_sec"])


async def test_field_department_without_gps_is_flagged(client, db_session):
    await _set_dept_field(db_session, "ENGINEERING", True)
    try:
        headers = await login(client, PHONES["w_eng"])
        r = await client.post(
            "/api/attendance/punch-in", json={"selfie_key": "f2.jpg"}, headers=headers
        )
        assert r.status_code == 200
        b = r.json()
        assert b["verification_level"] == "flagged"
        assert b["flagged_reason"] == "field_no_gps"
    finally:
        await _set_dept_field(db_session, "ENGINEERING", False)
        await _del_attendance(db_session, PHONES["w_eng"])


async def test_office_gps_path_verified_by_location(client, db_session):
    await _set_settings(db_session, gps_verify_enabled=True)
    try:
        headers = await login(client, PHONES["w_prod2"])
        r = await client.post(
            "/api/attendance/punch-in",
            json={**INSIDE, "gps_accuracy": 18, "selfie_key": "g1.jpg"},
            headers=headers,
        )
        assert r.status_code == 200
        b = r.json()
        assert b["verification_level"] == "verified"
        assert b["verification_path"] == "gps"
    finally:
        await _set_settings(db_session, gps_verify_enabled=False)
        await _del_attendance(db_session, PHONES["w_prod2"])


async def test_office_gps_path_inaccurate_is_flagged(client, db_session):
    await _set_settings(db_session, gps_verify_enabled=True, gps_accuracy_max_m=100)
    try:
        headers = await login(client, PHONES["w_prod3"])
        r = await client.post(
            "/api/attendance/punch-in",
            json={**INSIDE, "gps_accuracy": 350, "selfie_key": "g2.jpg"},
            headers=headers,
        )
        assert r.status_code == 200
        b = r.json()
        assert b["verification_level"] == "flagged"
        assert b["flagged_reason"].startswith("gps_inaccurate")
    finally:
        await _set_settings(db_session, gps_verify_enabled=False)
        await _del_attendance(db_session, PHONES["w_prod3"])


async def test_punch_out_source_manual(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    try:
        await client.post(
            "/api/attendance/punch-in",
            json={**INSIDE, "selfie_key": "m1.jpg", "ble_beacon_id": "aa:bb:cc:dd:ee:01"},
            headers=headers,
        )
        r = await client.post("/api/attendance/punch-out", headers=headers)
        assert r.status_code == 200
        assert r.json()["punch_out_source"] == "manual"
    finally:
        await _del_attendance(db_session, PHONES["w_prod1"])


async def test_daily_report_shape(client):
    headers = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/dashboard/daily-attendance", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "totals" in data and "departments" in data
    assert {"present", "absent", "flagged", "auto_punch_out", "late"} <= set(data["totals"])
