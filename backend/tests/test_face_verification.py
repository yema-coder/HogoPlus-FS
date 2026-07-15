"""Phase 4 Part B — face verification matrix (mocked Rekognition).

Covers: ≥90 pass, <80 flag+notify, 80-89 borderline, missing reference bootstrap,
Rekognition error → null (no flag), reset-reference endpoint, approval sets reference.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.models import Attendance, Employee, Notification
from app.tasks import _verify_face_async
from tests.conftest import PHONES, login

pytestmark = pytest.mark.asyncio


def _write_selfie(key: str) -> None:
    base = Path(settings.upload_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / key).write_bytes(b"\xff\xd8\xfffake-jpeg-bytes")


async def _make_attendance(db_session, phone: str, selfie_key: str, level="verified", day=1) -> Attendance:
    from datetime import date as date_cls

    emp = (
        await db_session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one()
    att = Attendance(
        employee_id=emp.id,
        date=date_cls(2030, 1, day),  # unique per test — avoids uq_attendance_emp_date clashes
        punch_in_at=datetime.now(timezone.utc),
        gps_lat=19.0, gps_lng=74.7, gps_verified=True,
        selfie_key=selfie_key, verification_level=level,
    )
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)
    _write_selfie(selfie_key)
    return att


async def _set_reference(db_session, phone: str, key: str | None) -> Employee:
    emp = (
        await db_session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one()
    emp.reference_selfie_key = key
    emp.reference_selfie_set_at = datetime.now(timezone.utc) if key else None
    await db_session.commit()
    if key:
        _write_selfie(key)
    return emp


async def test_score_90_plus_verifies(db_session, monkeypatch):
    await _set_reference(db_session, PHONES["w_att1"], "ref1.jpg")
    att = await _make_attendance(db_session, PHONES["w_att1"], "punch1.jpg", day=1)
    monkeypatch.setattr("app.aws.compare_faces", lambda a, b: 97.5)

    result = await _verify_face_async(str(att.id))
    assert result["face_verified"] is True

    await db_session.refresh(att)
    assert att.face_match_score == 97.5
    assert att.face_verified is True
    assert att.verification_level == "verified"  # unchanged


async def test_score_below_80_flags_and_notifies(db_session, monkeypatch):
    await _set_reference(db_session, PHONES["w_att2"], "ref2.jpg")
    att = await _make_attendance(db_session, PHONES["w_att2"], "punch2.jpg", day=2)
    monkeypatch.setattr("app.aws.compare_faces", lambda a, b: 42.0)

    result = await _verify_face_async(str(att.id))
    assert result["face_verified"] is False

    await db_session.refresh(att)
    assert att.face_verified is False
    assert att.verification_level == "flagged"
    assert att.flagged_reason == "face_mismatch"

    # Time Office manager notified
    time_mgr = (
        await db_session.execute(select(Employee).where(Employee.phone == PHONES["time_mgr"]))
    ).scalar_one()
    notes = (
        await db_session.execute(
            select(Notification).where(
                Notification.recipient_id == time_mgr.id,
                Notification.type == "attendance_face_mismatch",
            )
        )
    ).scalars().all()
    assert len(notes) >= 1


async def test_borderline_80_to_89_stores_score_only(db_session, monkeypatch):
    await _set_reference(db_session, PHONES["w_att3"], "ref3.jpg")
    att = await _make_attendance(db_session, PHONES["w_att3"], "punch3.jpg", day=3)
    monkeypatch.setattr("app.aws.compare_faces", lambda a, b: 85.0)

    result = await _verify_face_async(str(att.id))
    assert result["face_verified"] is None

    await db_session.refresh(att)
    assert att.face_match_score == 85.0
    assert att.face_verified is None
    assert att.verification_level == "verified"  # kept as-is
    assert att.flagged_reason is None


async def test_missing_reference_bootstraps(db_session, monkeypatch):
    emp = await _set_reference(db_session, PHONES["w_att4"], None)
    att = await _make_attendance(db_session, PHONES["w_att4"], "first_punch.jpg", day=4)

    called = []
    monkeypatch.setattr("app.aws.compare_faces", lambda a, b: called.append(1) or 99.0)

    result = await _verify_face_async(str(att.id))
    assert result.get("bootstrap") is True
    assert called == []  # no comparison on bootstrap punch

    await db_session.refresh(att)
    await db_session.refresh(emp)
    assert emp.reference_selfie_key == "first_punch.jpg"
    assert emp.reference_selfie_set_at is not None
    assert att.face_match_score is None
    assert att.face_verified is None
    # bootstrap lands in the Time Office queue for human confirmation
    assert att.verification_level == "flagged"
    assert att.flagged_reason == "reference_bootstrap"

    # audit event recorded
    row = (
        await db_session.execute(
            text("SELECT count(*) FROM audit_events WHERE action='employee.reference_selfie_bootstrap' AND entity_id=:e"),
            {"e": str(emp.id)},
        )
    ).scalar()
    assert row >= 1


async def test_rekognition_error_leaves_null_never_flags(db_session, monkeypatch):
    from app.aws import RekognitionUnavailable

    await _set_reference(db_session, PHONES["w_prod1"], "ref5.jpg")
    att = await _make_attendance(db_session, PHONES["w_prod1"], "punch5.jpg", day=5)

    def _boom(a, b):
        raise RekognitionUnavailable("timeout")

    monkeypatch.setattr("app.aws.compare_faces", _boom)

    result = await _verify_face_async(str(att.id))
    assert result == {"error": "rekognition_unavailable"}

    await db_session.refresh(att)
    assert att.face_match_score is None
    assert att.face_verified is None
    assert att.verification_level == "verified"  # NEVER flagged for infra failure
    assert att.flagged_reason is None


async def test_reset_reference_selfie_endpoint(client, db_session):
    emp = await _set_reference(db_session, PHONES["w_prod2"], "ref6.jpg")
    emp_id = str(emp.id)

    # worker cannot reset
    r = await client.post(
        f"/api/admin/employees/{emp_id}/reset-reference-selfie",
        headers=await login(client, PHONES["w_prod2"]),
    )
    assert r.status_code == 403

    # time office manager can
    r = await client.post(
        f"/api/admin/employees/{emp_id}/reset-reference-selfie",
        headers=await login(client, PHONES["time_mgr"]),
    )
    assert r.status_code == 200
    await db_session.refresh(emp)
    assert emp.reference_selfie_key is None
    assert emp.reference_selfie_set_at is None


async def test_flagged_queue_exposes_face_fields(client, db_session, monkeypatch):
    await _set_reference(db_session, PHONES["w_prod3"], "ref7.jpg")
    att = await _make_attendance(db_session, PHONES["w_prod3"], "punch7.jpg", day=7)
    monkeypatch.setattr("app.aws.compare_faces", lambda a, b: 30.0)
    await _verify_face_async(str(att.id))

    r = await client.get(
        "/api/attendance/flagged",
        headers=await login(client, PHONES["time_mgr"]),
    )
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == str(att.id))
    assert row["face_match_score"] == 30.0
    assert row["face_verified"] is False
    assert row["flagged_reason"] == "face_mismatch"
    assert row["selfie_url"]
    assert row["reference_selfie_url"]


async def test_bootstrap_approve_keeps_reference(client, db_session):
    emp = await _set_reference(db_session, PHONES["w_att1"], None)
    att = await _make_attendance(db_session, PHONES["w_att1"], "boot_a.jpg", day=8)
    await _verify_face_async(str(att.id))

    r = await client.post(
        f"/api/attendance/{att.id}/approve",
        headers=await login(client, PHONES["time_mgr"]),
    )
    assert r.status_code == 200
    await db_session.refresh(emp)
    assert emp.reference_selfie_key == "boot_a.jpg"  # human confirmed — reference stays


async def test_bootstrap_reject_clears_reference(client, db_session):
    emp = await _set_reference(db_session, PHONES["w_att2"], None)
    att = await _make_attendance(db_session, PHONES["w_att2"], "boot_r.jpg", day=9)
    await _verify_face_async(str(att.id))
    await db_session.refresh(emp)
    assert emp.reference_selfie_key == "boot_r.jpg"

    # worker cannot reject
    r = await client.post(
        f"/api/attendance/{att.id}/reject",
        headers=await login(client, PHONES["w_att2"]),
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/attendance/{att.id}/reject",
        headers=await login(client, PHONES["time_mgr"]),
    )
    assert r.status_code == 200
    assert r.json()["cleared_reference"] is True
    await db_session.refresh(emp)
    await db_session.refresh(att)
    assert emp.reference_selfie_key is None  # next punch re-bootstraps under supervision
    assert att.approved_by is not None  # leaves the pending queue
