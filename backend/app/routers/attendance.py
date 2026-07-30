import math
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
    Attendance,
    AttendanceRegularization,
    BleBeacon,
    Department,
    Employee,
    FactorySettings,
)
from app.notify import dispatcher, template
from app.schemas import BeaconAttachIn, BleDiagIn, PunchInIn, RegularizeDecideIn, RegularizeIn
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


@router.post("/attendance/{attendance_id}/attach-beacon")
async def attach_beacon(
    attendance_id: uuid.UUID,
    body: BeaconAttachIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """v1.0.17 SPEED PACK: the punch waits ≤5s for a beacon and never blocks. If the
    background zone scan matches AFTER submit, the app attaches it here — upgrading a
    location-flagged/verified row to verified_plus. Face-verification flags are never
    touched. Idempotent: a row that already has a beacon is returned unchanged."""
    rec = await session.get(Attendance, attendance_id)
    if rec is None or rec.employee_id != employee.id or bool(rec.is_demo) != bool(employee.is_demo):
        raise HTTPException(status_code=404, detail="Attendance record not found")
    if rec.ble_beacon_id:
        return _out(rec)
    if rec.punch_in_at is not None:
        punched = rec.punch_in_at if rec.punch_in_at.tzinfo else rec.punch_in_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - punched > timedelta(minutes=15):
            raise HTTPException(status_code=409, detail="Attach window closed")
    from app.ble import beacon_ref, resolve_beacon

    matched = await resolve_beacon(
        session,
        mac=body.ble_beacon_id,
        ibeacon_uuid=body.ble_ibeacon_uuid,
        major=body.ble_ibeacon_major,
        minor=body.ble_ibeacon_minor,
    )
    if matched is None:
        raise HTTPException(status_code=404, detail="Beacon not registered")
    rec.ble_beacon_id = beacon_ref(
        mac=body.ble_beacon_id,
        ibeacon_uuid=body.ble_ibeacon_uuid,
        major=body.ble_ibeacon_major,
        minor=body.ble_ibeacon_minor,
    )
    rec.ble_zone = matched.zone_label_en
    # BEACON WINS — but only over LOCATION-derived outcomes, never over face flags,
    # and never after Time Office has already reviewed the row.
    location_reasons = ("outside_geofence", "gps_missing", "no_beacon")
    if rec.approved_by is None and (
        rec.verification_level == "verified"
        or (
            rec.verification_level == "flagged"
            and (rec.flagged_reason or "").startswith(location_reasons)
        )
    ):
        rec.verification_level = "verified_plus"
        rec.flagged_reason = None
    await write_audit(
        session, employee.id, "attendance.beacon_attached", "attendance", str(rec.id),
        {"zone": rec.ble_zone, "level": rec.verification_level},
    )
    await session.commit()
    await session.refresh(rec)
    return _out(rec)


@router.post("/attendance/ble-diag")
async def submit_ble_diag(
    body: BleDiagIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """v1.0.16 field instrumentation: persist a raw on-device BLE diagnostic report
    (scan dump + permission states) as an audit event so beacon-detection failures
    can be analyzed server-side instead of described verbally. Read back via
    GET /api/admin/ble-diag (CGM/MD)."""
    import json as _json

    if len(_json.dumps(body.report, default=str)) > 150_000:
        raise HTTPException(status_code=413, detail="Report too large")
    await write_audit(session, employee.id, "ble.diag", "employee", str(employee.id), body.report)
    await session.commit()
    return {"stored": True}


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
    # nudge lifecycle: a late punch-out self-resolves the "no punch-out" flag
    # (only while Time Office hasn't touched it)
    if record.flagged_reason == "no_punch_out" and record.approved_by is None:
        record.flagged_reason = None
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
    # attach each punch's latest regularization request (worker sees the status)
    regs: dict[uuid.UUID, AttendanceRegularization] = {}
    if rows:
        reg_rows = (
            await session.execute(
                select(AttendanceRegularization)
                .where(AttendanceRegularization.attendance_id.in_([a.id for a in rows]))
                .order_by(AttendanceRegularization.created_at)
            )
        ).scalars().all()
        regs = {r.attendance_id: r for r in reg_rows}  # newest wins
    return [
        {
            **_out(a),
            "regularization": (
                {"id": str(regs[a.id].id), "status": regs[a.id].status}
                if a.id in regs
                else None
            ),
        }
        for a in rows
    ]


# ---------------- "My Month" + regularization (v1.0.21) ----------------

async def _month_counts(session: AsyncSession, employee_id: uuid.UUID, year: int, mon: int) -> dict:
    """THE single source of truth for monthly attendance counts. The worker's
    "My Month" card and the Time Office view both read THIS function — the two
    can never disagree. days_flagged_pending uses the exact same filter as the
    TO flagged queue (verification_level='flagged' AND approved_by IS NULL)."""
    start = datetime(year, mon, 1).date()
    end = datetime(year + (mon == 12), (mon % 12) + 1, 1).date()
    rows = (
        await session.execute(
            select(Attendance).where(
                Attendance.employee_id == employee_id,
                Attendance.date >= start,
                Attendance.date < end,
            )
        )
    ).scalars().all()
    return {
        "month": f"{year:04d}-{mon:02d}",
        "days_present": len({a.date for a in rows}),
        "days_flagged_pending": sum(
            1 for a in rows if a.verification_level == "flagged" and a.approved_by is None
        ),
        "days_flagged_resolved": sum(
            1 for a in rows if a.verification_level == "flagged" and a.approved_by is not None
        ),
        "days_late": sum(1 for a in rows if a.is_late),
        "days_complete": sum(1 for a in rows if a.punch_out_at is not None),
    }


@router.get("/attendance/month-summary")
async def month_summary(
    month: str | None = Query(default=None, description="YYYY-MM"),
    employee_id: uuid.UUID | None = Query(default=None),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Read-only "My Month" numbers + previous month for comparison. Workers see
    only themselves; Time Office / CGM / MD may pass employee_id."""
    target_id = employee.id
    if employee_id and employee_id != employee.id:
        if not await is_dept_manager(session, employee, "TIME_OFFICE"):
            raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
        target = await session.get(Employee, employee_id)
        if target is None or target.is_demo != employee.is_demo:
            raise HTTPException(status_code=404, detail="Employee not found")
        target_id = target.id
    if month:
        try:
            year, mon = map(int, month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        today = now_ist().date()
        year, mon = today.year, today.month
    prev_year, prev_mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    return {
        "employee_id": str(target_id),
        "current": await _month_counts(session, target_id, year, mon),
        "previous": await _month_counts(session, target_id, prev_year, prev_mon),
    }


REG_ALREADY_OPEN = {
    "code": "reg_already_open",
    "en": "A request for this punch is already pending.",
    "hi": "इस पंच के लिए अनुरोध पहले से लंबित है।",
    "mr": "या पंचसाठी विनंती आधीच प्रलंबित आहे.",
}


@router.post("/attendance/{attendance_id}/regularize")
async def request_regularization(
    attendance_id: uuid.UUID,
    body: RegularizeIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """One-tap "this punch is wrong" on a flagged punch (voice note optional).
    ONE open request per punch — DB-enforced. Routes to the Time Office queue
    with the original punch evidence attached."""
    record = await session.get(Attendance, attendance_id)
    if record is None or record.employee_id != employee.id:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    if record.verification_level != "flagged" and record.flagged_reason != "no_punch_out":
        raise HTTPException(status_code=409, detail="Only flagged punches can be disputed")
    if record.approved_by is not None:
        raise HTTPException(status_code=409, detail="This punch is already resolved")
    existing = (
        await session.execute(
            select(AttendanceRegularization).where(
                AttendanceRegularization.attendance_id == attendance_id,
                AttendanceRegularization.status == "open",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=REG_ALREADY_OPEN)
    reg = AttendanceRegularization(
        attendance_id=attendance_id,
        employee_id=employee.id,
        text_note=(body.text_note or "").strip() or None,
        voice_note_key=body.voice_note_key,
        status="open",
        is_demo=employee.is_demo,
    )
    session.add(reg)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()  # double-tap race — partial unique index caught it
        raise HTTPException(status_code=409, detail=REG_ALREADY_OPEN)
    await write_audit(
        session, employee.id, "attendance.regularization_requested",
        "attendance_regularization", str(reg.id),
        {"attendance_id": str(attendance_id), "date": record.date.isoformat()},
    )
    # notify the Time Office deciders (dept manager + TO Managers, same demo class)
    recipients: set[uuid.UUID] = set()
    to_dept = (
        await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
    ).scalar_one_or_none()
    if to_dept and to_dept.manager_employee_id:
        recipients.add(to_dept.manager_employee_id)
    to_managers = (
        await session.execute(
            select(Employee).where(
                Employee.role_code == "Manager",
                Employee.department_code == "TIME_OFFICE",
                Employee.is_demo == employee.is_demo,
            )
        )
    ).scalars().all()
    recipients.update(m.id for m in to_managers)
    title, nbody = template(
        "regularization_requested", f"{employee.full_name} — {record.date.isoformat()}"
    )
    for rid in recipients:
        await dispatcher.notify(
            session, rid, "regularization_requested", title, nbody,
            "attendance_regularization", str(reg.id),
        )
    await session.commit()
    return {"id": str(reg.id), "status": "open", "attendance_id": str(attendance_id)}


@router.get("/attendance/regularizations/mine")
async def my_regularizations(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(AttendanceRegularization, Attendance)
            .join(Attendance, AttendanceRegularization.attendance_id == Attendance.id)
            .where(AttendanceRegularization.employee_id == employee.id)
            .order_by(AttendanceRegularization.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "attendance_id": str(r.attendance_id),
            "date": a.date.isoformat(),
            "status": r.status,
            "text_note": r.text_note,
            "review_note": r.review_note,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r, a in rows
    ]


@router.get("/attendance/regularizations")
async def list_regularizations(
    status: str = Query(default="open"),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Time Office queue: each request carries the ORIGINAL punch evidence
    (selfie, GPS, zone, flag reason) alongside the worker's note."""
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
    if status not in ("open", "approved", "rejected"):
        raise HTTPException(status_code=422, detail="Invalid status filter")
    rows = (
        await session.execute(
            select(AttendanceRegularization, Attendance, Employee)
            .join(Attendance, AttendanceRegularization.attendance_id == Attendance.id)
            .join(Employee, AttendanceRegularization.employee_id == Employee.id)
            .where(
                AttendanceRegularization.status == status,
                AttendanceRegularization.is_demo == employee.is_demo,
            )
            .order_by(AttendanceRegularization.created_at.desc())
            .limit(100)
        )
    ).all()
    storage = get_storage()
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "text_note": r.text_note,
            "voice_note_url": f"/api/files/{r.voice_note_key}" if r.voice_note_key else None,
            "review_note": r.review_note,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "employee_name": w.full_name,
            "emp_id": w.emp_id,
            "department_code": w.department_code,
            # original punch evidence — the TO decides with full context
            "attendance": {
                **_out(a),
                "selfie_url": storage.url_for(a.selfie_key) if a.selfie_key else None,
                "reference_selfie_url": (
                    storage.url_for(w.reference_selfie_key) if w.reference_selfie_key else None
                ),
            },
        }
        for r, a, w in rows
    ]


@router.post("/attendance/regularizations/{reg_id}/decide")
async def decide_regularization(
    reg_id: uuid.UUID,
    body: RegularizeDecideIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Approve/reject a dispute. The underlying punch is resolved with EXACTLY
    the same state changes as the standalone approve/reject endpoints (one
    lifecycle, one source of truth); audited with the reviewer's name."""
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")
    reg = await session.get(AttendanceRegularization, reg_id)
    if reg is None or reg.is_demo != employee.is_demo:
        raise HTTPException(status_code=404, detail="Request not found")
    if reg.status != "open":
        raise HTTPException(status_code=409, detail="Request already decided")
    record = await session.get(Attendance, reg.attendance_id)
    cleared_reference = False
    if record is not None and record.verification_level == "flagged" and record.approved_by is None:
        record.approved_by = employee.id
        if body.action == "reject":
            # parity with POST /attendance/{id}/reject
            record.face_verified = False
            if record.flagged_reason == "reference_bootstrap":
                worker = await session.get(Employee, record.employee_id)
                if worker and worker.reference_selfie_key == record.selfie_key:
                    worker.reference_selfie_key = None
                    worker.reference_selfie_set_at = None
                    cleared_reference = True
    reg.status = "approved" if body.action == "approve" else "rejected"
    reg.reviewed_by = employee.id
    reg.reviewed_at = now_ist()
    reg.review_note = (body.note or "").strip() or None
    await write_audit(
        session, employee.id, f"attendance.regularization_{reg.status}",
        "attendance_regularization", str(reg.id),
        {
            "attendance_id": str(reg.attendance_id),
            "reviewer_name": employee.full_name,
            "note": reg.review_note,
            "cleared_reference": cleared_reference,
        },
    )
    date_str = record.date.isoformat() if record else ""
    nbody = (
        {"en": f"Approved ✓ — {date_str}", "hi": f"स्वीकृत ✓ — {date_str}", "mr": f"मंजूर ✓ — {date_str}"}
        if body.action == "approve"
        else {"en": f"Rejected ✗ — {date_str}", "hi": f"अस्वीकृत ✗ — {date_str}", "mr": f"नामंजूर ✗ — {date_str}"}
    )
    title, _ = template("regularization_decided")
    await dispatcher.notify(
        session, reg.employee_id, "regularization_decided", title, nbody,
        "attendance_regularization", str(reg.id),
    )
    await session.commit()
    return {"id": str(reg.id), "status": reg.status, "reviewed_by": str(employee.id)}


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
            # verification-flagged punches OR missing punch-outs (nudge escalation) —
            # both land in the same Time Office queue
            or_(
                Attendance.verification_level == "flagged",
                Attendance.flagged_reason == "no_punch_out",
            ),
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
    if record.verification_level != "flagged" and record.flagged_reason != "no_punch_out":
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
    if (
        record.verification_level != "flagged" and record.flagged_reason != "no_punch_out"
    ) or record.approved_by is not None:
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
