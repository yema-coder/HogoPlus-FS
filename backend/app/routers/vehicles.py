"""Wave 1 — Security vehicle entry/exit log (the gate register, digitised).

Feature-gated by settings.vehicle_log_enabled (default OFF); the demo bubble
bypasses the flag so demo screenshots/testing work before the real rollout.
Additive only — touches no auth/attendance/incident write path.
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Employee, FactorySettings, VehicleLog
from app.schemas import VehicleLogIn
from app.security import get_approved_employee
from app.shift_logic import IST, now_ist

router = APIRouter(tags=["vehicles"])

VEHICLE_TYPES = {"truck", "tractor", "tempo", "car", "bike", "bus", "jcb", "bullock_cart", "other"}
_PLATE_RE = re.compile(r"^[A-Z0-9 -]{3,15}$")


def _norm_plate(raw: str) -> str:
    """Uppercase and strip separators so 'mh-12 ab 1234' pairs with 'MH12AB1234'."""
    return re.sub(r"[\s-]", "", raw.upper())


async def _gate_access(session: AsyncSession, employee: Employee) -> None:
    if employee.department_code != "SECURITY" and employee.role.rank > 2:
        raise HTTPException(status_code=403, detail="Security staff only")
    if employee.is_demo:
        return  # demo bubble gets the feature first
    s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
    if not s or not s.vehicle_log_enabled:
        raise HTTPException(status_code=403, detail={"code": "feature_disabled"})


def _out(v: VehicleLog) -> dict:
    return {
        "id": str(v.id),
        "plate": v.plate,
        "vehicle_type": v.vehicle_type,
        "direction": v.direction,
        "driver_name": v.driver_name,
        "purpose": v.purpose,
        "photo_key": v.photo_key,
        "voice_note_key": v.voice_note_key,
        "gate_zone": v.gate_zone,
        "anpr_used": v.anpr_used,
        "paired_log_id": str(v.paired_log_id) if v.paired_log_id else None,
        "logged_at": v.logged_at.isoformat(),
    }


@router.post("/vehicles/log")
async def create_vehicle_log(
    body: VehicleLogIn,
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    await _gate_access(session, employee)
    plate = _norm_plate(body.plate)
    if not _PLATE_RE.match(plate):
        raise HTTPException(status_code=422, detail="Invalid plate")
    if body.vehicle_type not in VEHICLE_TYPES:
        raise HTTPException(status_code=422, detail="Invalid vehicle type")

    # offline outbox idempotency: same client_uuid replayed -> same row back
    if body.client_uuid:
        existing = (
            await session.execute(select(VehicleLog).where(VehicleLog.client_uuid == body.client_uuid))
        ).scalar_one_or_none()
        if existing:
            return {"log": _out(existing), "duplicate": True}

    logged_at = body.logged_at or datetime.now(timezone.utc)
    row = VehicleLog(
        plate=plate,
        vehicle_type=body.vehicle_type,
        direction=body.direction,
        driver_name=(body.driver_name or "").strip()[:100] or None,
        purpose=(body.purpose or "").strip()[:100] or None,
        photo_key=body.photo_key,
        voice_note_key=body.voice_note_key,
        gate_zone=(body.gate_zone or "").strip()[:100] or None,
        anpr_used=bool(body.anpr_used),
        logged_by=employee.id,
        client_uuid=body.client_uuid,
        is_demo=bool(employee.is_demo),
        logged_at=logged_at,
    )
    session.add(row)
    await session.flush()

    if body.direction == "out":
        open_in = (
            await session.execute(
                select(VehicleLog)
                .where(
                    VehicleLog.plate == plate,
                    VehicleLog.direction == "in",
                    VehicleLog.paired_log_id.is_(None),
                    VehicleLog.is_demo == bool(employee.is_demo),
                )
                .order_by(VehicleLog.logged_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if open_in:
            open_in.paired_log_id = row.id
            row.paired_log_id = open_in.id
    await session.commit()
    await session.refresh(row)
    return {"log": _out(row), "duplicate": False}


@router.get("/vehicles/last-mine")
async def last_vehicle_mine(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Same-as-last quick entry (v1.0.21): the guard's latest log. The PLATE is
    returned for EXPLICIT confirmation only — the client never auto-fills it
    (a stale plate is a wrong log)."""
    row = (
        await session.execute(
            select(VehicleLog)
            .where(VehicleLog.logged_by == employee.id, VehicleLog.is_demo == employee.is_demo)
            .order_by(VehicleLog.logged_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"log": None}
    return {
        "log": {
            "plate": row.plate,
            "vehicle_type": row.vehicle_type,
            "direction": row.direction,
            "driver_name": row.driver_name,
            "purpose": row.purpose,
            "logged_at": row.logged_at.isoformat(),
        }
    }


@router.get("/vehicles/logs")
async def list_vehicle_logs(
    day: str | None = None,
    plate: str | None = None,
    gate: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    await _gate_access(session, employee)
    q = select(VehicleLog).where(VehicleLog.is_demo == bool(employee.is_demo))
    if day:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
        start = datetime.combine(d, datetime.min.time(), tzinfo=IST)
        q = q.where(VehicleLog.logged_at >= start, VehicleLog.logged_at < start + timedelta(days=1))
    if plate:
        q = q.where(VehicleLog.plate.contains(_norm_plate(plate)))
    if gate:
        q = q.where(VehicleLog.gate_zone == gate)
    if direction in ("in", "out"):
        q = q.where(VehicleLog.direction == direction)
    rows = (
        (await session.execute(q.order_by(VehicleLog.logged_at.desc()).limit(min(limit, 500)).offset(offset)))
        .scalars()
        .all()
    )
    return [_out(v) for v in rows]


@router.get("/vehicles/inside")
async def vehicles_inside(
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    await _gate_access(session, employee)
    rows = (
        (
            await session.execute(
                select(VehicleLog)
                .where(
                    VehicleLog.direction == "in",
                    VehicleLog.paired_log_id.is_(None),
                    VehicleLog.is_demo == bool(employee.is_demo),
                )
                .order_by(VehicleLog.logged_at.asc())
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    out = []
    for v in rows:
        d = _out(v)
        d["hours_inside"] = round((now - v.logged_at).total_seconds() / 3600, 1)
        out.append(d)
    return out


@router.get("/vehicles/summary")
async def vehicles_summary(
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    await _gate_access(session, employee)
    start = datetime.combine(now_ist().date(), datetime.min.time(), tzinfo=IST)
    is_demo = bool(employee.is_demo)

    async def _count(*conds) -> int:
        return (
            await session.execute(select(func.count()).select_from(VehicleLog).where(*conds))
        ).scalar_one()

    today_in = await _count(
        VehicleLog.is_demo == is_demo, VehicleLog.direction == "in", VehicleLog.logged_at >= start
    )
    today_out = await _count(
        VehicleLog.is_demo == is_demo, VehicleLog.direction == "out", VehicleLog.logged_at >= start
    )
    inside = await _count(
        VehicleLog.is_demo == is_demo, VehicleLog.direction == "in", VehicleLog.paired_log_id.is_(None)
    )
    return {"today_in": today_in, "today_out": today_out, "currently_inside": inside}


@router.get("/vehicles/export.xlsx")
async def export_vehicle_register(
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    await _gate_access(session, employee)
    from openpyxl import Workbook

    q = select(VehicleLog, Employee.full_name).join(Employee, VehicleLog.logged_by == Employee.id).where(
        VehicleLog.is_demo == bool(employee.is_demo)
    )
    if date_from:
        start = datetime.combine(date.fromisoformat(date_from), datetime.min.time(), tzinfo=IST)
        q = q.where(VehicleLog.logged_at >= start)
    if date_to:
        end = datetime.combine(date.fromisoformat(date_to), datetime.min.time(), tzinfo=IST) + timedelta(days=1)
        q = q.where(VehicleLog.logged_at < end)
    rows = (await session.execute(q.order_by(VehicleLog.logged_at.asc()).limit(10000))).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Vehicle Register"
    ws.append(["Date (IST)", "Time (IST)", "Plate", "Type", "Direction", "Driver", "Purpose", "Gate", "Logged by", "ANPR", "Paired"])
    for v, guard_name in rows:
        local = v.logged_at.astimezone(IST)
        ws.append([
            local.strftime("%d-%m-%Y"), local.strftime("%H:%M"),
            v.plate, v.vehicle_type, v.direction.upper(),
            v.driver_name or "", v.purpose or "", v.gate_zone or "",
            guard_name, "yes" if v.anpr_used else "no",
            "yes" if v.paired_log_id else "no",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vehicle_register.xlsx"},
    )
