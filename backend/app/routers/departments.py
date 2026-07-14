from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Department

router = APIRouter(tags=["departments"])


@router.get("/departments")
async def list_departments(session: AsyncSession = Depends(get_session)):
    """Public read-only department list (needed during self-registration)."""
    depts = (
        await session.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.code))
    ).scalars().all()
    return [
        {
            "id": str(d.id),
            "code": d.code,
            "name_en": d.name_en,
            "name_hi": d.name_hi,
            "name_mr": d.name_mr,
            "has_manager": d.manager_employee_id is not None,
        }
        for d in depts
    ]
