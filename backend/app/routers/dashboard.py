"""MD Command Center read-only aggregate endpoints.

Access: Manager rank and above ONLY (rank<=3). Managers are scoped server-side to
their own department; CGM/MD (rank<=2) see everything. Never widened by the UI.
"""
import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, case as sa_case, cast as sa_cast, func as safunc, or_, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_session
from app.models import (
    Attendance,
    AuditEvent,
    Department,
    Employee,
    FormDefinition,
    FormSubmission,
    Incident,
    ShiftSwapRequest,
)
from app.security import get_approved_employee
from app.shift_logic import now_ist
from app.storage import get_storage

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/pulse")
async def factory_pulse(
    user: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Prompt 16: one warm AI sentence summarizing today's factory status (CGM/MD).
    Cached 10 min per class+language; static fallback if the LLM call fails."""
    if user.role.rank > 2:
        raise HTTPException(status_code=403, detail="CGM / MD only")
    from app.redis_client import redis_client

    lang = user.language_pref or "mr"
    cache_key = f"pulse:{int(user.is_demo)}:{lang}"
    cached = await redis_client.get(cache_key)
    if cached:
        return {"pulse": cached, "cached": True}

    today = now_ist().date()
    present = (
        await session.execute(
            select(safunc.count()).select_from(Attendance).where(
                Attendance.date == today, Attendance.is_demo == user.is_demo
            )
        )
    ).scalar() or 0
    total = (
        await session.execute(
            select(safunc.count()).select_from(Employee).where(
                Employee.is_active.is_(True), Employee.onboarding_status == "approved",
                Employee.is_demo == user.is_demo,
            )
        )
    ).scalar() or 0
    open_inc = (
        await session.execute(
            select(safunc.count()).select_from(Incident).where(
                Incident.status.in_(["submitted", "seen", "in_progress", "escalated"]),
                Incident.is_demo == user.is_demo,
            )
        )
    ).scalar() or 0
    crit_row = (
        await session.execute(
            select(Incident.department_code).where(
                Incident.severity == "critical",
                Incident.status.in_(["submitted", "seen", "in_progress", "escalated"]),
                Incident.is_demo == user.is_demo,
            ).limit(1)
        )
    ).scalar_one_or_none()
    pend_subs = (
        await session.execute(
            select(safunc.count()).select_from(FormSubmission).where(
                FormSubmission.status == "submitted", FormSubmission.is_demo == user.is_demo
            )
        )
    ).scalar() or 0

    pct = round(present * 100 / total) if total else 0
    lang_name = {"mr": "Marathi", "hi": "Hindi", "en": "English"}.get(lang, "Marathi")
    fallback = {
        "mr": f"आज: उपस्थिती {pct}% · {open_inc} खुल्या तक्रारी · {pend_subs} फॉर्म प्रलंबित"
              + (f" · १ गंभीर — {crit_row}" if crit_row else ""),
        "hi": f"आज: उपस्थिति {pct}% · {open_inc} खुली शिकायतें · {pend_subs} फॉर्म लंबित"
              + (f" · 1 गंभीर — {crit_row}" if crit_row else ""),
        "en": f"Today: attendance {pct}% · {open_inc} open complaints · {pend_subs} forms pending"
              + (f" · 1 critical — {crit_row}" if crit_row else ""),
    }.get(lang) or ""
    text = fallback
    try:
        from app import ai_core

        prompt = (
            f"Factory status today: attendance {present}/{total} ({pct}%), "
            f"{open_inc} open complaints, {pend_subs} form approvals pending"
            + (f", 1 CRITICAL incident in {crit_row}" if crit_row else "")
            + f". Write EXACTLY ONE short, warm sentence in {lang_name} for the MD's dashboard. "
              "Max 25 words. Plain text only, no preamble, no quotes."
        )
        out = await ai_core.chat_answer("You summarize a sugar factory's daily dashboard.", prompt)
        out = (out or "").strip().strip('"')
        if 0 < len(out) <= 300:
            text = out
            await ai_core.incr_usage("pulse", user.is_demo)
    except Exception:
        pass
    await redis_client.setex(cache_key, 600, text)
    return {"pulse": text, "cached": False}


@router.get("/plates/search")
async def plate_search(
    q: str = Query(min_length=2, max_length=20),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Vehicle plate search across incidents + form submissions (partial, case-insensitive).
    Manager (rank 3) sees only own-department results; CGM/MD see all."""
    rank = employee.role.rank
    if rank > 3:
        raise HTTPException(status_code=403, detail="Not allowed")
    needle = f"%{q.upper().replace(' ', '')}%"

    inc_q = select(Incident).where(
        Incident.detected_plate.ilike(needle), Incident.is_demo == employee.is_demo
    )
    sub_q = (
        select(FormSubmission, FormDefinition.title_en)
        .join(FormDefinition, FormSubmission.form_definition_id == FormDefinition.id)
        .where(
            FormSubmission.is_demo == employee.is_demo,
            sa_text(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(form_submissions.detected_plates) AS p "
                "WHERE p ILIKE :needle)"
            ).bindparams(needle=needle),
        )
    )
    if rank == 3:
        inc_q = inc_q.where(Incident.department_code == employee.department_code)
        sub_q = sub_q.where(FormSubmission.department_code == employee.department_code)

    incidents = (await session.execute(inc_q.order_by(Incident.created_at.desc()).limit(50))).scalars().all()
    subs = (await session.execute(sub_q.order_by(FormSubmission.created_at.desc()).limit(50))).all()

    results = [
        {
            "type": "incident",
            "id": str(i.id),
            "plate": i.detected_plate,
            "label": i.category,
            "department_code": i.department_code,
            "status": i.status,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in incidents
    ] + [
        {
            "type": "submission",
            "id": str(s.id),
            "plate": next((p for p in (s.detected_plates or []) if q.upper().replace(" ", "") in p.upper()), None),
            "label": title,
            "department_code": s.department_code,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s, title in subs
    ]
    results.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return {"query": q, "results": results}

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


async def _pending_counts(session: AsyncSession, dept: str | None, is_demo: bool) -> dict[str, int]:
    """pending approvals per department (submissions + registrations + swaps + incidents)."""
    counts: dict[str, int] = {}

    def add(rows):
        for dc, n in rows:
            if dc:
                counts[dc] = counts.get(dc, 0) + n

    q = select(FormSubmission.department_code, safunc.count()).where(
        FormSubmission.status == "submitted", FormSubmission.is_demo.is_(is_demo)
    ).group_by(FormSubmission.department_code)
    add((await session.execute(q)).all())

    q = select(Employee.department_code, safunc.count()).where(
        Employee.onboarding_status.in_(["self_registered", "pending_approval"]),
        Employee.is_demo.is_(is_demo),
    ).group_by(Employee.department_code)
    add((await session.execute(q)).all())

    q = (
        select(Employee.department_code, safunc.count())
        .select_from(ShiftSwapRequest)
        .join(Employee, ShiftSwapRequest.requester_id == Employee.id)
        .where(
            ShiftSwapRequest.status.in_(["pending_target", "pending_manager"]),
            ShiftSwapRequest.is_demo.is_(is_demo),
        )
        .group_by(Employee.department_code)
    )
    add((await session.execute(q)).all())

    q = select(Incident.department_code, safunc.count()).where(
        Incident.status.in_(["submitted", "escalated"]), Incident.is_demo.is_(is_demo)
    ).group_by(Incident.department_code)
    add((await session.execute(q)).all())

    if dept:
        counts = {dept: counts.get(dept, 0)}
    return counts


_OVERVIEW_CACHE: dict[tuple, tuple[float, dict]] = {}
_OVERVIEW_TTL = 45.0  # background warmer refreshes hot keys every 15s
OPEN_INCIDENT_STATUSES = ["submitted", "seen", "in_progress", "escalated"]


def _feed_item(i: Incident, reporter_name: str, storage) -> dict:
    return {
        "id": str(i.id), "category": i.category, "department_code": i.department_code,
        "reporter_name": reporter_name, "status": i.status, "severity": i.severity,
        "severity_reason": i.severity_reason, "detected_plate": i.detected_plate,
        "photo_url": storage.url_for(i.photo_key) if i.photo_key else None,
        "video_url": storage.url_for(i.video_key) if i.video_key else None,
        "voice_note_url": storage.url_for(i.voice_note_key) if i.voice_note_key else None,
        "address_text": i.address_text, "description": i.description,
        "created_at": i.created_at.isoformat(), "age_hours": _age_hours(i.created_at),
    }


@router.get("/incidents-feed")
async def incidents_feed(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    q: str | None = None,
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    """Prompt 18: paginated incident feed for the webdash landing view.
    Ordering is stable across pages: OPEN CRITICAL incidents first, then newest.
    `q` searches plate / category / department / reporter / description."""
    dept = _scope(user)
    storage = get_storage()
    base = (
        select(Incident, Employee.full_name)
        .join(Employee, Incident.reported_by == Employee.id)
        .where(Incident.is_demo == user.is_demo)
    )
    if dept:
        base = base.where(Incident.department_code == dept)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.where(
            or_(
                Incident.detected_plate.ilike(like),
                sa_cast(Incident.category, String).ilike(like),
                Incident.department_code.ilike(like),
                Employee.full_name.ilike(like),
                Incident.description.ilike(like),
                Incident.address_text.ilike(like),
            )
        )
    crit_first = sa_case(
        ((Incident.severity == "critical") & Incident.status.in_(OPEN_INCIDENT_STATUSES), 0),
        else_=1,
    )
    rows = (
        await session.execute(
            base.order_by(crit_first, Incident.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    items = [_feed_item(i, name, storage) for i, name in rows[:limit]]
    return {"items": items, "has_more": has_more, "offset": offset, "limit": limit}


@router.get("/overview")
async def overview(
    user: Employee = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_session),
):
    dept = _scope(user)
    cache_key = (dept, user.is_demo)
    hit = _OVERVIEW_CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < _OVERVIEW_TTL:
        return hit[1]
    return await compute_overview(dept, user.is_demo)


async def compute_overview(dept: str | None, is_demo: bool) -> dict:
    """Aggregate compute shared by the endpoint and the startup cache warmer."""
    today = now_ist().date()
    storage = get_storage()

    # Neon RTT is ~400ms per query — run all 10 aggregate queries CONCURRENTLY
    # on separate pooled connections instead of sequentially (Prompt 18 speed fix).
    async def run(stmt):
        async with SessionLocal() as s:
            return (await s.execute(stmt)).all()

    dept_q = select(Department).where(Department.is_active.is_(True)).order_by(Department.code)
    if dept:
        dept_q = dept_q.where(Department.code == dept)

    emp_q = select(Employee.department_code, safunc.count()).where(
        Employee.is_active.is_(True), Employee.onboarding_status == "approved",
        Employee.is_demo == is_demo,
    ).group_by(Employee.department_code)

    att_q = (
        select(Employee.department_code, Attendance.is_late, Attendance.verification_level, safunc.count())
        .select_from(Attendance)
        .join(Employee, Attendance.employee_id == Employee.id)
        .where(Attendance.date == today, Attendance.is_demo == is_demo)
        .group_by(Employee.department_code, Attendance.is_late, Attendance.verification_level)
    )

    inc_q = select(Incident.department_code, Incident.severity, safunc.count()).where(
        Incident.status.in_(OPEN_INCIDENT_STATUSES),
        Incident.is_demo == is_demo,
    ).group_by(Incident.department_code, Incident.severity)

    sub_q = select(FormSubmission.department_code, safunc.count()).where(
        safunc.date(FormSubmission.created_at) == today,
        FormSubmission.is_demo == is_demo,
    ).group_by(FormSubmission.department_code)

    # _pending_counts split into its 4 independent queries so they parallelize too
    p_sub_q = select(FormSubmission.department_code, safunc.count()).where(
        FormSubmission.status == "submitted", FormSubmission.is_demo.is_(is_demo)
    ).group_by(FormSubmission.department_code)
    p_reg_q = select(Employee.department_code, safunc.count()).where(
        Employee.onboarding_status.in_(["self_registered", "pending_approval"]),
        Employee.is_demo.is_(is_demo),
    ).group_by(Employee.department_code)
    p_swap_q = (
        select(Employee.department_code, safunc.count())
        .select_from(ShiftSwapRequest)
        .join(Employee, ShiftSwapRequest.requester_id == Employee.id)
        .where(
            ShiftSwapRequest.status.in_(["pending_target", "pending_manager"]),
            ShiftSwapRequest.is_demo.is_(is_demo),
        )
        .group_by(Employee.department_code)
    )
    p_inc_q = select(Incident.department_code, safunc.count()).where(
        Incident.status.in_(["submitted", "escalated"]), Incident.is_demo.is_(is_demo)
    ).group_by(Incident.department_code)

    feed_q = (
        select(Incident, Employee.full_name)
        .join(Employee, Incident.reported_by == Employee.id)
        .where(Incident.is_demo == is_demo)
        .order_by(Incident.created_at.desc())
        .limit(40)
    )
    if dept:
        feed_q = feed_q.where(Incident.department_code == dept)

    (
        dept_rows, emp_rows, att_rows, inc_rows, sub_rows,
        p_sub, p_reg, p_swap, p_inc, feed_rows,
    ) = await asyncio.gather(
        run(dept_q), run(emp_q), run(att_q), run(inc_q), run(sub_q),
        run(p_sub_q), run(p_reg_q), run(p_swap_q), run(p_inc_q), run(feed_q),
    )

    depts = [r[0] for r in dept_rows]
    totals = dict(emp_rows)

    att = {}
    for dc, late, level, n in att_rows:
        e = att.setdefault(dc, {"present": 0, "late": 0, "flagged": 0})
        e["present"] += n
        if late:
            e["late"] += n
        if level == "flagged":
            e["flagged"] += n

    open_inc = {}
    for dc, sev, n in inc_rows:
        e = open_inc.setdefault(dc, {"total": 0, "critical": 0})
        e["total"] += n
        if sev == "critical":
            e["critical"] += n

    subs = dict(sub_rows)

    pending: dict[str, int] = {}
    for rows in (p_sub, p_reg, p_swap, p_inc):
        for dc, n in rows:
            if dc:
                pending[dc] = pending.get(dc, 0) + n
    if dept:
        pending = {dept: pending.get(dept, 0)}

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

    feed = sorted(
        (_feed_item(i, name, storage) for i, name in feed_rows),
        key=lambda x: (SEV_RANK.get(x["severity"], 2), -datetime.fromisoformat(x["created_at"]).timestamp()),
    )[:15]

    payload = {"date": today.isoformat(), "kpis": kpis, "departments": tiles, "incidents": feed}
    _OVERVIEW_CACHE[(dept, is_demo)] = (time.monotonic(), payload)
    return payload


async def warm_overview_cache() -> None:
    """Prompt 18: keep the MD/CGM landing aggregates permanently hot (real + demo
    class, unscoped). Called every 15s by a startup task in main.py."""
    for is_demo in (False, True):
        await compute_overview(None, is_demo)


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
            .where(
                Employee.department_code == code,
                Attendance.date == target,
                Attendance.is_demo == user.is_demo,
            )
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
                FormSubmission.is_demo == user.is_demo,
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
                    Incident.is_demo == user.is_demo,
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
            "plate_status": i.plate_status,
            "plate_confidence": i.plate_confidence,
            "plate_source": i.plate_source,
            "plate_reason": i.plate_reason,
            "description": i.description,
            "address_text": i.address_text,
            "gps_lat": i.gps_lat,
            "gps_lng": i.gps_lng,
            "photo_url": storage.url_for(i.photo_key) if i.photo_key else None,
            "video_url": storage.url_for(i.video_key) if i.video_key else None,
            "voice_note_url": storage.url_for(i.voice_note_key) if i.voice_note_key else None,
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
                Employee.is_demo == user.is_demo,
            )
        )
    ).scalar() or 0
    att_trend_rows = (
        await session.execute(
            select(Attendance.date, safunc.count())
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(
                Employee.department_code == code, Attendance.date >= start,
                Attendance.date <= target, Attendance.is_demo == user.is_demo,
            )
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

    q = select(FormSubmission).where(
        FormSubmission.status == "submitted", FormSubmission.is_demo == user.is_demo
    )
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
        .where(
            ShiftSwapRequest.status.in_(["pending_target", "pending_manager"]),
            ShiftSwapRequest.is_demo == user.is_demo,
        )
    )
    if dept:
        q = q.where(Employee.department_code == dept)
    for sw, dc in (await session.execute(q)).all():
        items.append({"type": "shift_swap", "id": str(sw.id), "department_code": dc,
                      "manager": mgr_names.get(dc), "age_hours": _age_hours(sw.created_at),
                      "escalated": False, "created_at": sw.created_at.isoformat()})

    q = select(Incident).where(
        Incident.status.in_(["submitted", "escalated"]), Incident.is_demo == user.is_demo
    )
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

    # nightly PDF reports cover REAL factory data only — demo users get none
    if user.is_demo:
        return {"reports": []}
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
            .where(AuditEvent.is_demo == user.is_demo)
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
