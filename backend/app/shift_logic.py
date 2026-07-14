from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Shift, ShiftAssignment

IST = ZoneInfo("Asia/Kolkata")

# Departments whose Workers default to shift A
SHIFT_A_DEPARTMENTS = {"ENGINEERING", "PRODUCTION", "SECURITY", "DISTILLERY", "CANE_YARD"}

GRACE_MINUTES = 15


def now_ist() -> datetime:
    return datetime.now(IST)


async def resolve_shift_code(
    session: AsyncSession, employee_id, on_date: date
) -> str | None:
    """Swap override for the exact date wins; otherwise latest baseline <= date."""
    override = (
        await session.execute(
            select(ShiftAssignment).where(
                ShiftAssignment.employee_id == employee_id,
                ShiftAssignment.effective_date == on_date,
                ShiftAssignment.source == "swap",
            )
        )
    ).scalar_one_or_none()
    if override:
        return override.shift_code
    baseline = (
        await session.execute(
            select(ShiftAssignment)
            .where(
                ShiftAssignment.employee_id == employee_id,
                ShiftAssignment.effective_date <= on_date,
                ShiftAssignment.source == "baseline",
            )
            .order_by(ShiftAssignment.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return baseline.shift_code if baseline else None


async def get_shift(session: AsyncSession, code: str) -> Shift | None:
    return (
        await session.execute(select(Shift).where(Shift.code == code))
    ).scalar_one_or_none()


def is_late(punch_ist: datetime, attributed_date: date, shift_start: time) -> bool:
    start_dt = datetime.combine(attributed_date, shift_start, tzinfo=IST)
    return punch_ist > start_dt + timedelta(minutes=GRACE_MINUTES)
