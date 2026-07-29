"""Wave 1 — config-driven home screens.

GET /home/config resolves the widget layout for the caller's department+role:
(dept, role) > (dept, NULL) > (NULL, role) > None. A None config makes the app
render its built-in fallback home (today's behaviour, byte-identical).
Feature-gated by settings.home_config_enabled; demo bubble bypasses the flag.

GET /home/counts is ONE round trip returning every live number the wave-1
widgets need (cross-region DB makes per-widget fetches expensive).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    Attendance,
    Employee,
    FactorySettings,
    FormSubmission,
    HomeConfig,
    Incident,
    VehicleLog,
)
from app.schemas import HomeConfigUpsertIn
from app.security import get_approved_employee, require_role
from app.shift_logic import IST, now_ist

router = APIRouter(tags=["home"])


async def _resolve_config(session: AsyncSession, employee: Employee) -> dict | None:
    dept, role = employee.department_code, employee.role_code
    for d, r in ((dept, role), (dept, None), (None, role)):
        row = (
            await session.execute(
                select(HomeConfig).where(
                    HomeConfig.department_code.is_(d) if d is None else HomeConfig.department_code == d,
                    HomeConfig.role_code.is_(r) if r is None else HomeConfig.role_code == r,
                    HomeConfig.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row:
            return row.config_json
    return None


@router.get("/home/config")
async def get_home_config(
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    if not employee.is_demo:
        s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
        if not s or not s.home_config_enabled:
            return {"config": None}
    return {"config": await _resolve_config(session, employee)}


@router.get("/home/counts")
async def get_home_counts(
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(get_approved_employee),
):
    """Aggregate counts for home widgets — one request, role-aware."""
    is_demo = bool(employee.is_demo)
    rank = employee.role.rank
    counts: dict = {}

    async def _count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    today_start = datetime.combine(now_ist().date(), datetime.min.time(), tzinfo=IST)

    if rank <= 3 or employee.department_code == "TIME_OFFICE":  # TO clerks work the queues too
        counts["pending_registrations"] = await _count(
            select(func.count()).select_from(Employee).where(
                Employee.onboarding_status.in_(["self_registered", "pending_approval"]),
                Employee.is_demo == is_demo,
            )
        )
        counts["flagged_attendance"] = await _count(
            select(func.count()).select_from(Attendance).where(
                Attendance.verification_level == "flagged",
                Attendance.approved_by.is_(None),
                Attendance.is_demo == is_demo,
                Attendance.date >= (now_ist().date() - timedelta(days=7)),
            )
        )
        counts["phoneless_employees"] = await _count(
            select(func.count()).select_from(Employee).where(
                Employee.phone.is_(None), Employee.is_active.is_(True), Employee.is_demo == is_demo
            )
        )
        counts["pending_submissions"] = await _count(
            select(func.count()).select_from(FormSubmission).where(
                FormSubmission.status == "submitted", FormSubmission.is_demo == is_demo
            )
        )

    if rank <= 2:  # CGM/MD factory strip
        counts["present_today"] = await _count(
            select(func.count()).select_from(Attendance).where(
                Attendance.date == now_ist().date(), Attendance.is_demo == is_demo
            )
        )
        counts["open_incidents"] = await _count(
            select(func.count()).select_from(Incident).where(
                Incident.status != "resolved", Incident.is_demo == is_demo
            )
        )

    if employee.department_code == "SECURITY" or rank <= 2:
        counts["vehicles_today_in"] = await _count(
            select(func.count()).select_from(VehicleLog).where(
                VehicleLog.is_demo == is_demo,
                VehicleLog.direction == "in",
                VehicleLog.logged_at >= today_start,
            )
        )
        counts["vehicles_inside"] = await _count(
            select(func.count()).select_from(VehicleLog).where(
                VehicleLog.is_demo == is_demo,
                VehicleLog.direction == "in",
                VehicleLog.paired_log_id.is_(None),
            )
        )
    return counts


# ---- admin CRUD (CGM/MD) — this is how a department's home changes without an APK ----

@router.get("/admin/home-configs")
async def list_home_configs(
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(require_role(2)),
):
    rows = (await session.execute(select(HomeConfig))).scalars().all()
    return [
        {
            "id": str(r.id),
            "department_code": r.department_code,
            "role_code": r.role_code,
            "is_active": r.is_active,
            "config_json": r.config_json,
        }
        for r in rows
    ]


@router.put("/admin/home-configs")
async def upsert_home_config(
    body: HomeConfigUpsertIn,
    session: AsyncSession = Depends(get_session),
    employee: Employee = Depends(require_role(2)),
):
    if not isinstance(body.config_json, dict) or not isinstance(body.config_json.get("widgets"), list):
        raise HTTPException(status_code=422, detail="config_json must contain a widgets list")
    row = (
        await session.execute(
            select(HomeConfig).where(
                HomeConfig.department_code.is_(None)
                if body.department_code is None
                else HomeConfig.department_code == body.department_code,
                HomeConfig.role_code.is_(None) if body.role_code is None else HomeConfig.role_code == body.role_code,
            )
        )
    ).scalar_one_or_none()
    if row:
        row.config_json = body.config_json
        row.is_active = body.is_active
    else:
        row = HomeConfig(
            department_code=body.department_code,
            role_code=body.role_code,
            config_json=body.config_json,
            is_active=body.is_active,
        )
        session.add(row)
    await session.commit()
    return {"id": str(row.id), "saved": True}
