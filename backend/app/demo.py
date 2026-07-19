"""Demo showcase bubble helpers (Prompt 14).

Demo accounts (employees.is_demo=true) experience the FULL app on the live
system, but their data lives in a sealed bubble: every record they create is
tagged is_demo=true, every read query filters by the viewer's class, and
routing/notification fanout never crosses the boundary.

is_demo_seed=true marks permanent showcase data the hourly cleanup never touches.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, Employee


async def resolve_dept_manager_id(
    session: AsyncSession, dept: Department | None, is_demo: bool
) -> uuid.UUID | None:
    """Class-aware department manager: real records route to
    departments.manager_employee_id; demo records route to the demo Manager
    seeded for that department (never a real manager)."""
    if dept is None:
        return None
    if not is_demo:
        return dept.manager_employee_id
    mgr = (
        await session.execute(
            select(Employee)
            .where(
                Employee.department_code == dept.code,
                Employee.role_code == "Manager",
                Employee.is_demo.is_(True),
                Employee.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return mgr.id if mgr else None


async def get_role_holder(
    session: AsyncSession, role_code: str, is_demo: bool
) -> Employee | None:
    """Class-aware CGM/MD lookup — demo escalations/fanout go to the Demo CGM/MD."""
    return (
        await session.execute(
            select(Employee)
            .where(
                Employee.role_code == role_code,
                Employee.is_active.is_(True),
                Employee.is_demo.is_(is_demo),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
