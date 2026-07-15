"""MD Command Center read-only aggregate endpoints.

Access: Manager rank and above ONLY (rank<=3). Managers are scoped server-side to
their own department; CGM/MD (rank<=2) see everything. Never widened by the UI.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as safunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    Attendance,
    AuditEvent,
    Department,
    Employee,
    FormSubmission,
    Incident,
    ShiftSwapRequest,
)
from app.security import get_approved_employee
from app.shift_logic import now_ist
from app.storage import get_storage

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SEV_RANK = {"critical": 0, "high": 1, "normal": 2}


async def get_dashboard_user(
    employee: Employee = Depends(get_approved_employee),
) -> Employee:
    if employee.role is None or employee.role.rank > 3:
        raise HTTPException(status_code=403, detail="Manager / CGM / MD only")
    return employee


def _scope(user: Employee) -> str | None:
    """department_code filter for managers; None = all (CGM/MD)."""
    return None if user.role.rank <= 2 else user.department_code


def _age_hours(dt) -> float:
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)


async def _pending_counts(session: AsyncSession, dept: str | None) -> dict[str, int]:
    """pending approvals per department (submissions + registrations + swaps + incidents)."""
    counts: dict[str, int] = {}

    def add(rows):
        for dc, n in rows:
            if dc:
                counts[dc] = counts.get(dc, 0) + n

    q = select(FormSubmission.department_code, safunc.count()).where(
        FormSubmission.status == "submitted"
    ).group_by(FormSubmission.department_code)
    add((await session.execute(q)).all())

    q = select(Employee.department_code, safunc.count()).where(
        Employee.onboarding_status.in_(["self_registered", "pending_approval"])
    ).group_by(Employee.department_code)
    add((await session.execute(q)).all())

    q = (
        select(Employee.department_code, safunc.count())
        .select_from(ShiftSwapRequest)
        .join(Employee, ShiftSwapRequest.requester_id == Employee.id)
        .where(ShiftSwapRequest.status.in_(["pending_target", "pending_manager"]))
        .group_by(Employee.department_code)
    )
    add((await session.execute(q)).all())

    q = select(Incident.department_code, safunc.count()).where(
        Incident.status.in_(["submitted", "escalated"])
    ).group_by(Incident.department_code)
    add((await session.execute(q)).all())

    if dept:
        counts = {dept: counts.get(dept, 0)}
    return counts


@router.get("/overview")
async def overview(
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    dept = _scope(user)
    today = now_ist().date()
    storage = get_storage()

    dept_q = select(Department).where(Department.is_active.is_(True)).order_by(Department.code)
    if dept:
        dept_q = dept_q.where(Department.code == dept)
    depts = (await session.execute(dept_q)).scalars().all()

    emp_q = select(Employee.department_code, safunc.count()).where(
        Employee.is_active.is_(True), Employee.onboarding_status == "approved"
    ).group_by(Employee.department_code)
    totals = dict((await session.execute(emp_q)).all())

    att_q = (
        select(Employee.department_code, Attendance.is_late, Attendance.verification_level, safunc.count())
        .select_from(Attendance)
        .join(Employee, Attendance.employee_id == Employee.id)
        .where(Attendance.date == today)
        .group_by(Employee.department_code, Attendance.is_late, Attendance.verification_level)
    )
    att = {}
    for dc, late, level, n in (await session.execute(att_q)).all():
        e = att.setdefault(dc, {"present": 0, "late": 0, "flagged": 0})
        e["present"] += n
        if late:
            e["late"] += n
        if level == "flagged":
            e["flagged"] += n

    inc_q = select(Incident.department_code, Incident.severity, safunc.count()).where(
        Incident.status.in_(["submitted", "seen", "in_progress", "escalated"])
    ).group_by(Incident.department_code, Incident.severity)
    open_inc = {}
    for dc, sev, n in (await session.execute(inc_q)).all():
        e = open_inc.setdefault(dc, {"total": 0, "critical": 0})
        e["total"] += n
        if sev == "critical":
            e["critical"] += n

    sub_q = select(FormSubmission.department_code, safunc.count()).where(
        safunc.date(FormSubmission.created_at) == today
    ).group_by(FormSubmission.department_code)
    subs = dict((await session.execute(sub_q)).all())

    pending = await _pending_counts(session, dept)

    tiles = []
    for d in depts:
        total = totals.get(d.code, 0)
        a = att.get(d.code, {"present": 0, "late": 0, "flagged": 0})
        oi = open_inc.get(d.code, {"total": 0, "critical": 0})
        pct = round(a["present"] * 100 / total) if total else 0
        p = pending.get(d.code, 0)
        health = "red" if oi["critical"] else ("amber" if (p > 5 or pct < 60) else "green")
        tiles.append({
            "code": d.code, "name_en": d.name_en, "name_hi": d.name_hi, "name_mr": d.name_mr,
            "total": total, "present": a["present"], "attendance_pct": pct,
            "open_incidents": oi["total"], "critical_incidents": oi["critical"],
            "pending_approvals": p, "submissions_today": subs.get(d.code, 0), "health": health,
        })

    visible = [d.code for d in depts]
    kpis = {
        "present": sum(t["present"] for t in tiles),
        "total": sum(t["total"] for t in tiles),
        "late": sum(att.get(c, {}).get("late", 0) for c in visible),
        "flagged": sum(att.get(c, {}).get("flagged", 0) for c in visible),
        "open_incidents": sum(t["open_incidents"] for t in tiles),
        "critical_incidents": sum(t["critical_incidents"] for t in tiles),
        "pending_approvals": sum(t["pending_approvals"] for t in tiles),
        "submissions_today": sum(t["submissions_today"] for t in tiles),
    }
    kpis["attendance_pct"] = round(kpis["present"] * 100 / kpis["total"]) if kpis["total"] else 0

    feed_q = (
        select(Incident, Employee.full_name)
        .join(Employee, Incident.reported_by == Employee.id)
        .order_by(Incident.created_at.desc())
        .limit(40)
    )
    if dept:
        feed_q = feed_q.where(Incident.department_code == dept)
    rows = (await session.execute(feed_q)).all()
    feed = sorted(
        (
            {
                "id": str(i.id), "category": i.category, "department_code": i.department_code,
                "reporter_name": name, "status": i.status, "severity": i.severity,
                "severity_reason": i.severity_reason, "detected_plate": i.detected_plate,
                "photo_url": storage.url_for(i.photo_key) if i.photo_key else None,
                "created_at": i.created_at.isoformat(), "age_hours": _age_hours(i.created_at),
            }
            for i, name in rows
        ),
        key=lambda x: (SEV_RANK.get(x["severity"], 2), -datetime.fromisoformat(x["created_at"]).timestamp()),
    )[:15]

    return {"date": today.isoformat(), "kpis": kpis, "departments": tiles, "incidents": feed}


@router.get("/department/{code}")
async def department_detail(
    code: str,
    date: str | None = Query(default=None),
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    scope = _scope(user)
    if scope and scope != code:
        raise HTTPException(status_code=403, detail="Managers can only view their own department")
    dept = (await session.execute(select(Department).where(Department.code == code))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    target = datetime.fromisoformat(date).date() if date else now_ist().date()
    storage = get_storage()

    manager = await session.get(Employee, dept.manager_employee_id) if dept.manager_employee_id else None

    att_rows = (
        await session.execute(
            select(Attendance, Employee.full_name, Employee.emp_id)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(Employee.department_code == code, Attendance.date == target)
            .order_by(Attendance.punch_in_at)
        )
    ).all()
    attendance = [
        {
            "id": str(a.id), "name": name, "emp_id": emp_id,
            "punch_in_at": a.punch_in_at.isoformat() if a.punch_in_at else None,
            "punch_out_at": a.punch_out_at.isoformat() if a.punch_out_at else None,
            "verification_level": a.verification_level, "is_late": a.is_late,
            "flagged_reason": a.flagged_reason, "face_match_score": a.face_match_score,
            "approved_by": str(a.approved_by) if a.approved_by else None,
        }
        for a, name, emp_id in att_rows
    ]

    sub_rows = (
        await session.execute(
            select(FormSubmission, Employee.full_name)
            .join(Employee, FormSubmission.submitted_by == Employee.id)
            .where(
                FormSubmission.department_code == code,
                safunc.date(FormSubmission.created_at) == target,
            )
            .order_by(FormSubmission.created_at.desc())
        )
    ).all()
    submissions = [
        {
            "id": str(s.id), "submitted_by_name": name, "status": s.status,
            "created_at": s.created_at.isoformat(), "data": s.data_json,
            "photos": [storage.url_for(k) for k in (s.photos or [])],
        }
        for s, name in sub_rows
    ]

    inc_rows = (
        (
            await session.execute(
                select(Incident).where(
                    Incident.department_code == code,
                    Incident.status.in_(["submitted", "seen", "in_progress", "escalated"]),
                ).order_by(Incident.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    incidents = [
        {
            "id": str(i.id), "category": i.category, "status": i.status,
            "severity": i.severity, "created_at": i.created_at.isoformat(),
            "detected_plate": i.detected_plate,
        }
        for i in inc_rows
    ]

    # trends: last 14 days
    start = target - timedelta(days=13)
    total_emp = (
        await session.execute(
            select(safunc.count()).select_from(Employee).where(
                Employee.department_code == code, Employee.is_active.is_(True),
                Employee.onboarding_status == "approved",
            )
        )
    ).scalar() or 0
    att_trend_rows = (
        await session.execute(
            select(Attendance.date, safunc.count())
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(Employee.department_code == code, Attendance.date >= start, Attendance.date <= target)
            .group_by(Attendance.date)
        )
    ).all()
    att_by_day = {d.isoformat(): n for d, n in att_trend_rows}
    sub_trend_rows = (
        await session.execute(
            select(safunc.date(FormSubmission.created_at), safunc.count())
            .where(
                FormSubmission.department_code == code,
                safunc.date(FormSubmission.created_at) >= start,
            )
            .group_by(safunc.date(FormSubmission.created_at))
        )
    ).all()
    sub_by_day = {d.isoformat(): n for d, n in sub_trend_rows}
    trends = []
    for i in range(14):
        day = (start + timedelta(days=i)).isoformat()
        present = att_by_day.get(day, 0)
        trends.append({
            "date": day,
            "attendance_pct": round(present * 100 / total_emp) if total_emp else 0,
            "submissions": sub_by_day.get(day, 0),
        })

    return {
        "code": code, "name_en": dept.name_en, "name_hi": dept.name_hi, "name_mr": dept.name_mr,
        "manager_name": manager.full_name if manager else None,
        "date": target.isoformat(), "total_employees": total_emp,
        "attendance": attendance, "submissions": submissions, "incidents": incidents,
        "trends": trends,
    }


@router.get("/approvals-aging")
async def approvals_aging(
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    dept = _scope(user)
    items = []

    mgr_names: dict[str, str | None] = {}
    for d in (await session.execute(select(Department))).scalars().all():
        if d.manager_employee_id:
            m = await session.get(Employee, d.manager_employee_id)
            mgr_names[d.code] = m.full_name if m else None
        else:
            mgr_names[d.code] = None

    q = select(FormSubmission).where(FormSubmission.status == "submitted")
    if dept:
        q = q.where(FormSubmission.department_code == dept)
    for s in (await session.execute(q)).scalars().all():
        items.append({"type": "form_submission", "id": str(s.id), "department_code": s.department_code,
                      "manager": mgr_names.get(s.department_code), "age_hours": _age_hours(s.created_at),
                      "escalated": False, "created_at": s.created_at.isoformat()})

    q = select(Employee).where(Employee.onboarding_status.in_(["self_registered", "pending_approval"]))
    if dept:
        q = q.where(Employee.department_code == dept)
    for e in (await session.execute(q)).scalars().all():
        items.append({"type": "registration", "id": str(e.id), "department_code": e.department_code,
                      "manager": mgr_names.get(e.department_code), "age_hours": _age_hours(e.created_at),
                      "escalated": False, "created_at": e.created_at.isoformat()})

    q = (
        select(ShiftSwapRequest, Employee.department_code)
        .join(Employee, ShiftSwapRequest.requester_id == Employee.id)
        .where(ShiftSwapRequest.status.in_(["pending_target", "pending_manager"]))
    )
    if dept:
        q = q.where(Employee.department_code == dept)
    for sw, dc in (await session.execute(q)).all():
        items.append({"type": "shift_swap", "id": str(sw.id), "department_code": dc,
                      "manager": mgr_names.get(dc), "age_hours": _age_hours(sw.created_at),
                      "escalated": False, "created_at": sw.created_at.isoformat()})

    q = select(Incident).where(Incident.status.in_(["submitted", "escalated"]))
    if dept:
        q = q.where(Incident.department_code == dept)
    for i in (await session.execute(q)).scalars().all():
        items.append({"type": "incident", "id": str(i.id), "department_code": i.department_code,
                      "manager": mgr_names.get(i.department_code), "age_hours": _age_hours(i.created_at),
                      "escalated": i.status == "escalated", "created_at": i.created_at.isoformat()})

    items.sort(key=lambda x: -x["age_hours"])

    by_mgr: dict[str, dict] = {}
    for it in items:
        key = it["manager"] or f"— ({it['department_code']})"
        e = by_mgr.setdefault(key, {"manager": it["manager"], "department_code": it["department_code"],
                                    "pending": 0, "oldest_hours": 0.0})
        e["pending"] += 1
        e["oldest_hours"] = max(e["oldest_hours"], it["age_hours"])
    summary = sorted(by_mgr.values(), key=lambda x: -x["oldest_hours"])

    return {"items": items, "summary": summary}


@router.get("/reports")
async def reports_list(
    user: Employee = Depends(get_dashboard_user),
):
    if user.role.rank > 2:
        raise HTTPException(status_code=403, detail="CGM / MD only")
    from app.config import settings
    from app.storage import S3Storage

    if settings.file_storage_mode != "s3":
        return {"reports": []}
    s3 = S3Storage()
    resp = s3.client.list_objects_v2(Bucket=s3.bucket, Prefix="reports/")
    out = []
    for obj in resp.get("Contents", []):
        key = obj["Key"]  # reports/YYYY-MM-DD/factory-report-{lang}.pdf
        parts = key.split("/")
        if len(parts) != 3:
            continue
        lang = parts[2].replace("factory-report-", "").replace(".pdf", "")
        out.append({"key": key, "date": parts[1], "lang": lang, "url": s3.url_for(key),
                    "size": obj.get("Size", 0)})
    out.sort(key=lambda x: (x["date"], x["lang"]), reverse=True)
    return {"reports": out}


@router.get("/audit")
async def audit_trail(
    limit: int = Query(default=100, le=200),
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    if user.role.rank > 2:
        raise HTTPException(status_code=403, detail="CGM / MD only")
    rows = (
        await session.execute(
            select(AuditEvent, Employee.full_name)
            .outerjoin(Employee, AuditEvent.actor_id == Employee.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(a.id), "actor": name, "action": a.action, "entity_type": a.entity_type,
            "entity_id": a.entity_id, "detail": a.detail_json,
            "created_at": a.created_at.isoformat(),
        }
        for a, name in rows
    ]
