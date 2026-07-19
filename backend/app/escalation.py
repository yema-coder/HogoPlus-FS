"""Time-based escalation sweep. Callable from Celery beat and from tests.

Demo bubble: the sweep runs per class — real stale items escalate to the real
CGM/MD, demo stale items to the Demo CGM/MD. Never across the boundary."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.config import settings
from app.demo import get_role_holder
from app.models import FormSubmission, Incident, IncidentTimeline
from app.notify import dispatcher, template

logger = logging.getLogger("hogo.escalation")


async def run_escalation_sweep(session: AsyncSession) -> dict:
    counts = {"incidents_escalated": 0, "incidents_to_md": 0, "submissions_escalated": 0}
    for is_demo in (False, True):
        c = await _sweep_class(session, is_demo)
        for k in counts:
            counts[k] += c[k]
    return counts


async def _sweep_class(session: AsyncSession, is_demo: bool) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=settings.escalation_hours)
    cgm = await get_role_holder(session, "CGM", is_demo)
    md = await get_role_holder(session, "MD", is_demo)
    counts = {"incidents_escalated": 0, "incidents_to_md": 0, "submissions_escalated": 0}

    if cgm is None:
        if not is_demo:
            logger.warning("No active CGM found; escalation sweep skipped")
        return counts

    # 1) Stale incidents -> escalate to CGM
    stale = (
        await session.execute(
            select(Incident).where(
                Incident.status.in_(["submitted", "seen"]),
                Incident.created_at < cutoff,
                Incident.is_demo.is_(is_demo),
            )
        )
    ).scalars().all()
    for inc in stale:
        inc.status = "escalated"
        inc.escalated_to = cgm.id
        inc.escalated_at = now
        session.add(
            IncidentTimeline(
                incident_id=inc.id, actor_id=None, event="escalated",
                detail_json={"escalated_to": str(cgm.id), "level": "CGM"},
            )
        )
        title, body = template("incident_escalated", f"Incident {inc.category} pending > {settings.escalation_hours}h")
        await dispatcher.notify(session, cgm.id, "incident_escalated", title, body, "incident", str(inc.id))
        await write_audit(session, None, "incident.escalated", "incident", str(inc.id), {"to": "CGM"}, is_demo=is_demo)
        counts["incidents_escalated"] += 1

    # 2) Incidents already with CGM for another window -> escalate to MD (if MD exists;
    #    gracefully stay with CGM otherwise)
    with_cgm = (
        await session.execute(
            select(Incident).where(
                Incident.status == "escalated",
                Incident.escalated_to == cgm.id,
                Incident.escalated_at < cutoff,
                Incident.is_demo.is_(is_demo),
            )
        )
    ).scalars().all()
    for inc in with_cgm:
        if md is None:
            continue  # no MD yet — item remains with CGM
        inc.escalated_to = md.id
        inc.escalated_at = now
        session.add(
            IncidentTimeline(
                incident_id=inc.id, actor_id=None, event="escalated",
                detail_json={"escalated_to": str(md.id), "level": "MD"},
            )
        )
        title, body = template("incident_escalated", "Incident escalated to MD")
        await dispatcher.notify(session, md.id, "incident_escalated", title, body, "incident", str(inc.id))
        await write_audit(session, None, "incident.escalated", "incident", str(inc.id), {"to": "MD"}, is_demo=is_demo)
        counts["incidents_to_md"] += 1

    # 3) Stale form submissions -> escalate to CGM
    stale_subs = (
        await session.execute(
            select(FormSubmission).where(
                FormSubmission.status == "submitted",
                FormSubmission.created_at < cutoff,
                FormSubmission.is_demo.is_(is_demo),
            )
        )
    ).scalars().all()
    for sub in stale_subs:
        sub.status = "escalated"
        sub.escalated_to = cgm.id
        sub.escalated_at = now
        title, body = template("submission_escalated", f"Form submission pending > {settings.escalation_hours}h")
        await dispatcher.notify(session, cgm.id, "submission_escalated", title, body, "form_submission", str(sub.id))
        await write_audit(session, None, "form_submission.escalated", "form_submission", str(sub.id), {"to": "CGM"}, is_demo=is_demo)
        counts["submissions_escalated"] += 1

    return counts
