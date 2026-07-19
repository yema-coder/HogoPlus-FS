"""Hourly demo-bubble cleanup (Prompt 14).

Judge-created records (is_demo=true AND is_demo_seed=false) live ~1 hour, then
are purged together with their R2 media. Seed showcase rows (is_demo_seed=true)
persist forever. Real data (is_demo=false) is NEVER touched.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func as safunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    AuditEvent,
    ChatMessage,
    Employee,
    FormSubmission,
    Incident,
    IncidentTimeline,
    Notification,
    ShiftSwapRequest,
)

logger = logging.getLogger("hogo.demo_cleanup")

DEMO_MAX_AGE_MINUTES = 60


async def run_demo_cleanup(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    include_seed: bool = False,
    older_than_minutes: int | None = DEMO_MAX_AGE_MINUTES,
    now: datetime | None = None,
    delete_media: bool = True,
) -> dict:
    """Delete demo records (never real ones). Scheduler: 60-min age, seed spared.
    Admin purge: older_than_minutes=None (all ages), optional include_seed."""
    now = now or datetime.now(timezone.utc)

    def scoped(model):
        cond = [model.is_demo.is_(True)]
        if not include_seed:
            cond.append(model.is_demo_seed.is_(False))
        if older_than_minutes is not None:
            cond.append(model.created_at < now - timedelta(minutes=older_than_minutes))
        return cond

    counts: dict[str, int] = {}
    media_keys: set[str] = set()

    incidents = (await session.execute(select(Incident).where(*scoped(Incident)))).scalars().all()
    for i in incidents:
        for k in (i.photo_key, i.video_key, i.voice_note_key, i.resolution_photo_key):
            if k:
                media_keys.add(k)
    subs = (
        await session.execute(select(FormSubmission).where(*scoped(FormSubmission)))
    ).scalars().all()
    for s in subs:
        media_keys.update(k for k in (s.photos or []) if k)
    atts = (await session.execute(select(Attendance).where(*scoped(Attendance)))).scalars().all()
    for a in atts:
        if a.selfie_key:
            media_keys.add(a.selfie_key)

    # never delete media that is someone's active face reference (bootstrap selfies)
    refs = (
        await session.execute(
            select(Employee.reference_selfie_key).where(Employee.reference_selfie_key.is_not(None))
        )
    ).scalars().all()
    media_keys -= set(refs)

    counts["incidents"] = len(incidents)
    counts["form_submissions"] = len(subs)
    counts["attendance"] = len(atts)
    simple_tables = (
        (ShiftSwapRequest, "shift_swaps"),
        (Notification, "notifications"),
        (AuditEvent, "audit_events"),
        (ChatMessage, "chat_messages"),
    )
    for model, name in simple_tables:
        counts[name] = (
            await session.execute(select(safunc.count()).select_from(model).where(*scoped(model)))
        ).scalar() or 0
    counts["media_objects"] = len(media_keys)

    if dry_run:
        return {"dry_run": True, **counts}

    inc_ids = [i.id for i in incidents]
    if inc_ids:
        await session.execute(delete(IncidentTimeline).where(IncidentTimeline.incident_id.in_(inc_ids)))
        await session.execute(delete(Incident).where(Incident.id.in_(inc_ids)))
    if subs:
        await session.execute(delete(FormSubmission).where(FormSubmission.id.in_([s.id for s in subs])))
    if atts:
        await session.execute(delete(Attendance).where(Attendance.id.in_([a.id for a in atts])))
    for model, _ in simple_tables:
        await session.execute(delete(model).where(*scoped(model)))
    await session.commit()

    if delete_media and media_keys:
        from starlette.concurrency import run_in_threadpool

        from app.storage import get_storage

        storage = get_storage()
        for key in media_keys:
            try:
                await run_in_threadpool(storage.delete, key)
            except Exception:
                logger.warning("demo cleanup: failed deleting media %s", key)

    if any(v for k, v in counts.items()):
        logger.info("demo cleanup: purged %s", counts)
    return {"dry_run": False, **counts}
