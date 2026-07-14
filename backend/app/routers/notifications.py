import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Employee, Notification
from app.security import get_current_employee

router = APIRouter(tags=["notifications"])


def _out(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "type": n.type,
        "title_en": n.title_en,
        "title_hi": n.title_hi,
        "title_mr": n.title_mr,
        "body_en": n.body_en,
        "body_hi": n.body_hi,
        "body_mr": n.body_mr,
        "entity_type": n.entity_type,
        "entity_id": n.entity_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/notifications/mine")
async def my_notifications(
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.recipient_id == employee.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    unread = sum(1 for n in rows if not n.is_read)
    return {"items": [_out(n) for n in rows], "unread_count": unread}


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    n = await session.get(Notification, notification_id)
    if n is None or n.recipient_id != employee.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    await session.commit()
    return _out(n)
