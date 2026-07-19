import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, Employee


async def write_audit(
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    detail: dict | None = None,
    is_demo: bool | None = None,
) -> None:
    # demo bubble: audit rows inherit the actor's class (session.get hits the
    # identity map — the actor is almost always already loaded in this session)
    if is_demo is None:
        is_demo = False
        if actor_id is not None:
            actor = await session.get(Employee, actor_id)
            is_demo = bool(actor.is_demo) if actor else False
    session.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            detail_json=detail or {},
            is_demo=is_demo,
        )
    )
