import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import Attendance, Department, Employee, FactorySettings
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


@router.post("/attendance/punch-in")
async def punch_in(
    body: PunchInIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    fs = await _factory_settings(session)
    now_utc = datetime.now(timezone.utc)
    ist_now = now_ist()

    # verification level
    inside = False
    flagged_reason = None
    if body.gps_lat is None or body.gps_lng is None:
        level = "flagged"
        flagged_reason = "gps_missing"
    else:
        distance = _haversine_m(body.gps_lat, body.gps_lng, fs.factory_lat, fs.factory_lng)
        inside = distance <= fs.radius_meters
        if not inside:
            level = "flagged"
            flagged_reason = f"outside_geofence({int(distance)}m)"
        elif body.ble_beacon_id:
            level = "verified_plus"
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
        date=att_date,
        punch_in_at=now_utc,
        gps_lat=body.gps_lat,
        gps_lng=body.gps_lng,
        gps_verified=inside,
        ble_beacon_id=body.ble_beacon_id,
        ble_zone=body.ble_zone,
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

    # Face verification runs ASYNC in Celery — the punch response is never delayed.
    # The task also handles the bootstrap rule (first selfie becomes the reference).
    try:
        from app.tasks import verify_face_task

        verify_face_task.delay(str(record.id))
    except Exception:  # broker unavailable must never fail a punch
        pass

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
        .where(Attendance.verification_level == "flagged", Attendance.approved_by.is_(None))
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
            .where(Employee.department_code == code, Attendance.date == target)
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
    if record is None:
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
            .where(Attendance.date == target)
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
