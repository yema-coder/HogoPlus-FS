import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import Department, Employee, Incident, IncidentTimeline
from app.notify import dispatcher, template
from app.schemas import ConfirmRoutingIn, IncidentCreateIn, IncidentStatusIn
from app.security import get_approved_employee, get_current_employee, is_dept_manager

router = APIRouter(tags=["incidents"])


def _out(i: Incident) -> dict:
    return {
        "id": str(i.id),
        "reported_by": str(i.reported_by),
        "department_code": i.department_code,
        "category": i.category,
        "photo_key": i.photo_key,
        "photo_url": f"/api/files/{i.photo_key}" if i.photo_key else None,
        "video_key": i.video_key,
        "video_url": f"/api/files/{i.video_key}" if i.video_key else None,
        "gps_lat": i.gps_lat,
        "gps_lng": i.gps_lng,
        "address_text": i.address_text,
        "description": i.description,
        "voice_note_key": i.voice_note_key,
        "status": i.status,
        "severity": i.severity,
        "severity_reason": i.severity_reason,
        "assigned_manager_id": str(i.assigned_manager_id) if i.assigned_manager_id else None,
        "escalated_to": str(i.escalated_to) if i.escalated_to else None,
        "escalated_at": i.escalated_at.isoformat() if i.escalated_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "resolution_note": i.resolution_note,
        "resolution_photo_key": i.resolution_photo_key,
        "resolution_photo_url": f"/api/files/{i.resolution_photo_key}" if i.resolution_photo_key else None,
        "ai_suggested_category": i.ai_suggested_category,
        "ai_suggested_department": i.ai_suggested_department,
        "ai_suggested_severity": i.ai_suggested_severity,
        "ai_confidence": i.ai_confidence,
        "ai_confirmed_by": i.ai_confirmed_by,
        "detected_plate": i.detected_plate,
        "plate_status": i.plate_status,
        "plate_confidence": i.plate_confidence,
        "plate_source": i.plate_source,
        "plate_reason": i.plate_reason,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _timeline_out(t: IncidentTimeline) -> dict:
    return {
        "id": str(t.id),
        "actor_id": str(t.actor_id) if t.actor_id else None,
        "event": t.event,
        "detail_json": t.detail_json,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("/incidents")
async def create_incident(
    body: IncidentCreateIn,
    background: BackgroundTasks,
    employee: Employee = Depends(get_current_employee),  # pending users MAY report incidents
    session: AsyncSession = Depends(get_session),
):
    dept = (
        await session.execute(select(Department).where(Department.code == body.department_code))
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")

    assigned = dept.manager_employee_id
    if assigned is None:
        cgm = (
            await session.execute(
                select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        assigned = cgm.id if cgm else None

    incident = Incident(
        reported_by=employee.id,
        department_code=body.department_code,
        category=body.category,
        photo_key=body.photo_key,
        video_key=body.video_key,
        gps_lat=body.gps_lat,
        gps_lng=body.gps_lng,
        address_text=body.address_text,
        description=body.description,
        voice_note_key=body.voice_note_key,
        severity=body.severity,
        assigned_manager_id=assigned,
        status="submitted",
        plate_status="pending" if body.photo_key else None,
    )
    session.add(incident)
    await session.flush()
    session.add(
        IncidentTimeline(
            incident_id=incident.id, actor_id=employee.id, event="created",
            detail_json={"category": body.category, "severity": body.severity},
        )
    )
    if assigned and body.category != "other":
        # explicit category → route immediately (legacy path). 'other' waits for
        # AI suggestion + worker confirmation (or the 10-minute timeout).
        title, notif_body = template("incident_assigned", f"{body.category} — {dept.name_en}")
        await dispatcher.notify(session, assigned, "incident_assigned", title, notif_body, "incident", str(incident.id))
        incident.ai_confirmed_by = "explicit"
    await write_audit(session, employee.id, "incident.created", "incident", str(incident.id), {"category": body.category})
    await session.commit()
    await session.refresh(incident)

    # AI classification (category+dept+severity) + opportunistic ANPR run AFTER the
    # response, IN-PROCESS. Production containers have no Celery worker (root cause of
    # the "plate chip never appears" bug) — never depend on a broker for incident AI.
    # Video incidents: classifier uses text+audio only; ANPR only for photos.
    if not os.environ.get("TESTING"):
        from app.tasks import run_incident_ai_background

        background.add_task(run_incident_ai_background, str(incident.id), bool(incident.photo_key))

    return _out(incident)


async def apply_incident_routing(
    session: AsyncSession,
    incident: Incident,
    category: str,
    department_code: str,
    severity: str,
    confirmed_by: str,
    actor_id=None,
) -> None:
    """Apply final routing (worker confirm / change / AI timeout): set fields,
    reassign the department manager, notify, and record the timeline entry."""
    dept = (
        await session.execute(select(Department).where(Department.code == department_code))
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    incident.category = category
    incident.department_code = department_code
    incident.severity = severity
    incident.ai_confirmed_by = confirmed_by
    assigned = dept.manager_employee_id
    if assigned is None:
        cgm = (
            await session.execute(
                select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        assigned = cgm.id if cgm else None
    incident.assigned_manager_id = assigned
    session.add(
        IncidentTimeline(
            incident_id=incident.id, actor_id=actor_id, event="routed",
            detail_json={"category": category, "department_code": department_code,
                         "severity": severity, "confirmed_by": confirmed_by},
        )
    )
    if assigned:
        title, notif_body = template("incident_assigned", f"{category} — {dept.name_en}")
        await dispatcher.notify(session, assigned, "incident_assigned", title, notif_body, "incident", str(incident.id))
    if severity == "critical":
        tops = (
            await session.execute(select(Employee).where(Employee.is_active.is_(True)))
        ).scalars().all()
        title, notif_body = template("incident_critical", f"{category} — {dept.name_en}")
        for e in tops:
            if e.role and e.role.rank <= 2 and e.id != assigned:
                await dispatcher.notify(session, e.id, "incident_critical", title, notif_body, "incident", str(incident.id))


@router.post("/incidents/{incident_id}/confirm-routing")
async def confirm_routing(
    incident_id: uuid.UUID,
    body: ConfirmRoutingIn,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.reported_by != employee.id and employee.role.rank > 3:
        raise HTTPException(status_code=403, detail="Not allowed")
    if incident.ai_confirmed_by in ("worker", "worker_changed", "ai_timeout"):
        raise HTTPException(status_code=409, detail="Routing already confirmed")
    category = body.category or incident.ai_suggested_category or incident.category
    department_code = body.department_code or incident.ai_suggested_department or incident.department_code
    severity = body.severity or incident.ai_suggested_severity or incident.severity
    changed = bool(body.category or body.department_code) and (
        category != incident.ai_suggested_category or department_code != incident.ai_suggested_department
    )
    confirmed_by = "worker_changed" if changed else "worker"
    await apply_incident_routing(session, incident, category, department_code, severity, confirmed_by, employee.id)
    await write_audit(session, employee.id, "incident.routed", "incident", str(incident.id),
                      {"category": category, "department_code": department_code, "confirmed_by": confirmed_by})
    await session.commit()
    await session.refresh(incident)
    return _out(incident)


@router.get("/incidents/mine")
async def my_incidents(
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Incident).where(Incident.reported_by == employee.id).order_by(Incident.created_at.desc())
        )
    ).scalars().all()
    return [_out(i) for i in rows]


@router.get("/incidents/{incident_id}")
async def incident_detail(
    incident_id: uuid.UUID,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    allowed = (
        incident.reported_by == employee.id
        or incident.assigned_manager_id == employee.id
        or incident.escalated_to == employee.id
        or await is_dept_manager(session, employee, incident.department_code)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    timeline = (
        await session.execute(
            select(IncidentTimeline)
            .where(IncidentTimeline.incident_id == incident.id)
            .order_by(IncidentTimeline.created_at.asc())
        )
    ).scalars().all()
    return {**_out(incident), "timeline": [_timeline_out(t) for t in timeline]}


@router.get("/incidents")
async def list_incidents(
    department_code: str | None = None,
    status: str | None = None,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    query = select(Incident)
    rank = employee.role.rank
    if rank <= 2:
        if department_code:
            query = query.where(Incident.department_code == department_code)
    elif rank == 3:
        query = query.where(Incident.department_code == employee.department_code)
    else:
        query = query.where(Incident.reported_by == employee.id)
    if status:
        query = query.where(Incident.status == status)
    rows = (await session.execute(query.order_by(Incident.created_at.desc()))).scalars().all()
    return [_out(i) for i in rows]


@router.post("/incidents/{incident_id}/status")
async def change_status(
    incident_id: uuid.UUID,
    body: IncidentStatusIn,
    background: BackgroundTasks,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    allowed = (
        incident.assigned_manager_id == employee.id
        or incident.escalated_to == employee.id
        or await is_dept_manager(session, employee, incident.department_code)
    )
    if not allowed or employee.role.rank > 3:
        raise HTTPException(status_code=403, detail="Only Manager/CGM/MD can update incident status")

    old_status = incident.status
    if body.status == "resolved":
        if not body.resolution_photo_key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "resolution_photo_required",
                    "en": "A resolution photo is required to mark this resolved.",
                    "hi": "समाधान की फ़ोटो ज़रूरी है।",
                    "mr": "निराकरणाचा फोटो आवश्यक आहे.",
                },
            )
        incident.resolved_at = datetime.now(timezone.utc)
        incident.resolution_note = body.note
        incident.resolution_photo_key = body.resolution_photo_key
    incident.status = body.status
    event = "seen" if body.status == "seen" else "status_change"
    session.add(
        IncidentTimeline(
            incident_id=incident.id, actor_id=employee.id, event=event,
            detail_json={"from": old_status, "to": body.status, "note": body.note},
        )
    )
    await write_audit(
        session, employee.id, "incident.status_change", "incident", str(incident.id),
        {"from": old_status, "to": body.status},
    )
    title, notif_body = template("incident_status", f"{old_status} → {body.status}")
    await dispatcher.notify(session, incident.reported_by, "incident_status", title, notif_body, "incident", str(incident.id))
    await session.commit()
    await session.refresh(incident)
    if body.status == "resolved" and incident.resolution_photo_key and not os.environ.get("TESTING"):
        from app.tasks import run_plate_detection_background

        background.add_task(run_plate_detection_background, "incident", str(incident.id))
    return _out(incident)
