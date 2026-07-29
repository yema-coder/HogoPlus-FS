import math
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import Attendance, BleBeacon, Department, Employee, FactorySettings
from app.notify import dispatcher, template
from app.schemas import PunchInIn
from app.security import get_approved_employee, is_dept_manager, require_role
from app.shift_logic import IST, get_shift, is_late, now_ist, resolve_shift_code
from app.storage import get_storage

router = APIRouter(tags=["attendance"])


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _out(a: Attendance) -> dict:
    return {
        "id": str(a.id),
        "employee_id": str(a.employee_id),
        "date": a.date.isoformat(),
        "punch_in_at": a.punch_in_at.isoformat() if a.punch_in_at else None,
        "punch_out_at": a.punch_out_at.isoformat() if a.punch_out_at else None,
        "gps_lat": a.gps_lat,
        "gps_lng": a.gps_lng,
        "gps_verified": a.gps_verified,
        "ble_beacon_id": a.ble_beacon_id,
        "ble_zone": a.ble_zone,
        "selfie_key": a.selfie_key,
        "verification_level": a.verification_level,
        "shift_code": a.shift_code,
        "is_late": a.is_late,
        "flagged_reason": a.flagged_reason,
        "face_match_score": a.face_match_score,
        "face_verified": a.face_verified,
        "approved_by": str(a.approved_by) if a.approved_by else None,
    }


async def _factory_settings(session: AsyncSession) -> FactorySettings:
    s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=500, detail="Factory settings not seeded")
    return s


@router.get("/attendance/beacon-macs")
async def beacon_macs(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Active registered beacon MACs — the mobile scanner matches detected devices against these."""
    macs = (
        await session.execute(
            select(BleBeacon.mac_address).where(
                BleBeacon.is_active.is_(True), BleBeacon.mac_address.is_not(None)
            )
        )
    ).scalars().all()
    return {"macs": macs}


@router.get("/attendance/beacon-registry")
async def beacon_registry(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Dual-mode registry for the mobile scanner: active registered MACs AND
    active registered iBeacon (UUID/Major/Minor) triples. The scanner matches a
    detected device if EITHER its MAC or its iBeacon triple is in this list.
    v1.0.15: entries carry trilingual zone labels so the app can show a live
    zone chip at capture time (older builds ignore the extra keys)."""
    rows = (
        await session.execute(
            select(BleBeacon).where(BleBeacon.is_active.is_(True))
        )
    ).scalars().all()
    macs = [b.mac_address for b in rows if b.mac_address]
    ibeacons = [
        {
            "uuid": b.beacon_uuid, "major": b.major, "minor": b.minor,
            "zone_en": b.zone_label_en, "zone_hi": b.zone_label_hi, "zone_mr": b.zone_label_mr,
        }
        for b in rows
        if b.beacon_uuid and b.major is not None and b.minor is not None
    ]
    macs_detail = [
        {
            "mac": b.mac_address,
            "zone_en": b.zone_label_en, "zone_hi": b.zone_label_hi, "zone_mr": b.zone_label_mr,
        }
        for b in rows
        if b.mac_address
    ]
    return {"macs": macs, "ibeacons": ibeacons, "macs_detail": macs_detail}


@router.post("/attendance/punch-in")
async def punch_in(
    body: PunchInIn,
    background: BackgroundTasks,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    fs = await _factory_settings(session)
    now_utc = datetime.now(timezone.utc)
    ist_now = now_ist()

    # Dual-mode BLE (Prompt: MAC + iBeacon): the app sends whichever identifier it
    # matched against the registered list; the backend resolves the zone from the
    # registered active beacon. Unregistered/inactive → None (GPS-only level).
    from app.ble import beacon_ref, resolve_beacon

    matched_beacon = await resolve_beacon(
        session,
        mac=body.ble_beacon_id,
        ibeacon_uuid=body.ble_ibeacon_uuid,
        major=body.ble_ibeacon_major,
        minor=body.ble_ibeacon_minor,
    )
    # record the identifier the app reported (audit), regardless of registration
    scanned_ref = beacon_ref(
        mac=body.ble_beacon_id,
        ibeacon_uuid=body.ble_ibeacon_uuid,
        major=body.ble_ibeacon_major,
        minor=body.ble_ibeacon_minor,
    )

    # verification level — BEACON WINS (launch order 2026-07-27): a matched registered
    # beacon is physical proof of presence (beacons are mounted inside the factory),
    # so it yields verified_plus even when GPS drifts outside the geofence or is
    # missing. Geofence/GPS flagging applies ONLY when no beacon was matched.
    inside = False
    distance = None
    flagged_reason = None
    if body.gps_lat is not None and body.gps_lng is not None:
        distance = _haversine_m(body.gps_lat, body.gps_lng, fs.factory_lat, fs.factory_lng)
        inside = distance <= fs.radius_meters
    if matched_beacon:
        level = "verified_plus"
    elif fs.beacon_first_mode:
        # BEACON-FIRST POLICY (settings flag, ships OFF): the beacon zone is the
        # PRIMARY location identity. GPS is still captured and stored as secondary
        # evidence (gps_verified keeps the geofence truth) but never decides the
        # outcome — a no-beacon punch is ACCEPTED and flagged for Time Office review.
        level = "flagged"
        flagged_reason = (
            "no_beacon_gps_only"
            if body.gps_lat is not None and body.gps_lng is not None
            else "no_beacon_no_gps"
        )
    elif body.gps_lat is None or body.gps_lng is None:
        level = "flagged"
        flagged_reason = "gps_missing"
    elif not inside:
        level = "flagged"
        flagged_reason = f"outside_geofence({int(distance)}m)"
    else:
        level = "verified"

    # attribute date: with the corrected windows (C = 00:00–08:00) every shift's
    # punch-in window sits inside a single calendar day, so a 01:30 punch belongs
    # to the C shift of the calendar day that just started at 00:00.
    att_date = ist_now.date()
    shift_code = await resolve_shift_code(session, employee.id, att_date)

    existing = (
        await session.execute(
            select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date == att_date)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Already punched in for this day")

    late = False
    if shift_code:
        shift = await get_shift(session, shift_code)
        if shift:
            late = is_late(ist_now, att_date, shift.start_time)

    record = Attendance(
        employee_id=employee.id,
        is_demo=employee.is_demo,
        date=att_date,
        punch_in_at=now_utc,
        gps_lat=body.gps_lat,
        gps_lng=body.gps_lng,
        gps_verified=inside,
        ble_beacon_id=scanned_ref,
        ble_zone=matched_beacon.zone_label_en if matched_beacon else None,
        selfie_key=body.selfie_key,
        verification_level=level,
        shift_code=shift_code,
        is_late=late,
        flagged_reason=flagged_reason,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Already punched in for this day")
    await session.refresh(record)

    # Face verification runs AFTER the response, IN-PROCESS (production containers
    # have no Celery worker). Handles the bootstrap rule (first selfie = reference).
    if not os.environ.get("TESTING"):
        from app.tasks import run_face_verification_background

        background.add_task(run_face_verification_background, str(record.id))

    return _out(record)


@router.post("/attendance/punch-out")
async def punch_out(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    today = now_ist().date()
    record = (
        await session.execute(
            select(Attendance)
            .where(
                Attendance.employee_id == employee.id,
                Attendance.punch_out_at.is_(None),
                Attendance.date.in_([today, today - timedelta(days=1)]),
            )
            .order_by(Attendance.date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="No open punch-in found")
    record.punch_out_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(record)
    return _out(record)


@router.get("/attendance/mine")
async def my_attendance(
    month: str | None = Query(default=None, description="YYYY-MM"),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    if month:
        try:
            year, mon = map(int, month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        today = now_ist().date()
        year, mon = today.year, today.month
    start = datetime(year, mon, 1).date()
    end = datetime(year + (mon == 12), (mon % 12) + 1, 1).date()
    rows = (
        await session.execute(
            select(Attendance)
            .where(Attendance.employee_id == employee.id, Attendance.date >= start, Attendance.date < end)
            .order_by(Attendance.date.desc())
        )
    ).scalars().all()
    return [_out(a) for a in rows]


@router.get("/attendance/flagged")
async def flagged_attendance(
    date: str | None = Query(default=None),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
    query = (
        select(
            Attendance,
            Employee.full_name,
            Employee.emp_id,
            Employee.department_code,
            Employee.reference_selfie_key,
        )
        .join(Employee, Attendance.employee_id == Employee.id)
        .where(
            Attendance.verification_level == "flagged",
            Attendance.approved_by.is_(None),
            Attendance.is_demo == employee.is_demo,
        )
    )
    if date:
        query = query.where(Attendance.date == datetime.fromisoformat(date).date())
    rows = (await session.execute(query.order_by(Attendance.date.desc()))).all()
    storage = get_storage()
    return [
        {
            **_out(a),
            "employee_name": name,
            "emp_id": emp_id,
            "department_code": dept,
            "selfie_url": storage.url_for(a.selfie_key) if a.selfie_key else None,
            "reference_selfie_url": storage.url_for(ref_key) if ref_key else None,
        }
        for a, name, emp_id, dept, ref_key in rows
    ]


@router.get("/attendance/department/{code}")
async def department_attendance(
    code: str,
    date: str | None = Query(default=None),
    employee: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    if employee.role.rank == 3 and not await is_dept_manager(session, employee, code):
        raise HTTPException(status_code=403, detail="Managers can only view their own department")
    target = datetime.fromisoformat(date).date() if date else now_ist().date()
    rows = (
        await session.execute(
            select(Attendance, Employee.full_name, Employee.emp_id)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(
                Employee.department_code == code,
                Attendance.date == target,
                Attendance.is_demo == employee.is_demo,
            )
            .order_by(Attendance.punch_in_at)
        )
    ).all()
    return [{**_out(a), "employee_name": name, "emp_id": emp_id} for a, name, emp_id in rows]


@router.post("/attendance/{attendance_id}/approve")
async def approve_flagged(
    attendance_id: uuid.UUID,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
    record = await session.get(Attendance, attendance_id)
    if record is None or record.is_demo != employee.is_demo:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    if record.verification_level != "flagged":
        raise HTTPException(status_code=409, detail="Only flagged records need approval")
    record.approved_by = employee.id
    await write_audit(session, employee.id, "attendance.approved", "attendance", str(record.id), {})
    title, body = template("attendance_approved", record.date.isoformat())
    await dispatcher.notify(session, record.employee_id, "attendance_approved", title, body, "attendance", str(record.id))
    await session.commit()
    await session.refresh(record)
    return _out(record)


@router.post("/attendance/{attendance_id}/reject")
async def reject_flagged(
    attendance_id: uuid.UUID,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Reject a flagged punch. For reference_bootstrap rows this ALSO clears the
    just-set reference selfie so the next punch re-bootstraps under supervision."""
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
    record = await session.get(Attendance, attendance_id)
    if record is None or record.is_demo != employee.is_demo:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    if record.verification_level != "flagged" or record.approved_by is not None:
        raise HTTPException(status_code=409, detail="Only pending flagged records can be rejected")
    record.approved_by = employee.id
    record.face_verified = False
    cleared_reference = False
    if record.flagged_reason == "reference_bootstrap":
        worker = await session.get(Employee, record.employee_id)
        if worker and worker.reference_selfie_key == record.selfie_key:
            worker.reference_selfie_key = None
            worker.reference_selfie_set_at = None
            cleared_reference = True
    await write_audit(
        session, employee.id, "attendance.rejected", "attendance", str(record.id),
        {"cleared_reference": cleared_reference},
    )
    await session.commit()
    await session.refresh(record)
    return {**_out(record), "rejected": True, "cleared_reference": cleared_reference}


@router.get("/dashboard/attendance-summary")
async def attendance_summary(
    date: str | None = Query(default=None),
    employee: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    target = datetime.fromisoformat(date).date() if date else now_ist().date()
    rows = (
        await session.execute(
            select(Attendance, Employee.department_code)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(Attendance.date == target, Attendance.is_demo == employee.is_demo)
        )
    ).all()
    depts = (await session.execute(select(Department.code))).scalars().all()
    summary = {code: {"department_code": code, "present": 0, "late": 0, "flagged": 0} for code in depts}
    for att, dept_code in rows:
        entry = summary.setdefault(dept_code, {"department_code": dept_code, "present": 0, "late": 0, "flagged": 0})
        entry["present"] += 1
        if att.is_late:
            entry["late"] += 1
        if att.verification_level == "flagged":
            entry["flagged"] += 1
    return {"date": target.isoformat(), "departments": sorted(summary.values(), key=lambda x: x["department_code"])}
