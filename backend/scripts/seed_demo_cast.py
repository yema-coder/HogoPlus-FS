"""Prompt 14: seed the 28-account demo cast (idempotent — safe to re-run).

13 Demo Workers  : +919000000001..013 (alphabetical dept order)
13 Demo Managers : +919000000101..113 (same order = worker + 100)
Demo CGM         : +919000000500 (dashboard password printed)
Demo MD          : +919000000600 (dashboard password printed)

All accounts have is_demo=true → they log in with the fixed demo OTP 123456
(no SMS ever sent) and live in the sealed demo data bubble.

Run: cd /app/backend && python scripts/seed_demo_cast.py
"""
import asyncio
import secrets
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Employee, ShiftAssignment

DEPTS = [
    "ACCOUNTS", "ADMIN", "AGRICULTURE", "CANE_YARD", "CIVIL", "DISTILLERY",
    "ENGINEERING", "GODOWN", "PRODUCTION", "PURCHASE", "SECURITY", "STORE", "TIME_OFFICE",
]
BASELINE_DATE = date(2025, 1, 1)


def _title(dept: str) -> str:
    return dept.replace("_", " ").title()


def cast() -> list[dict]:
    people = []
    for i, dept in enumerate(DEPTS, start=1):
        people.append({
            "emp_id": f"D{i:03d}", "phone": f"+91{9000000000 + i}",
            "full_name": f"Demo {_title(dept)} Worker", "department_code": dept,
            "role_code": "Worker", "designation": f"Demo Worker — {_title(dept)}",
        })
        people.append({
            "emp_id": f"D{100 + i}", "phone": f"+91{9000000100 + i}",
            "full_name": f"Demo {_title(dept)} Manager", "department_code": dept,
            "role_code": "Manager", "designation": f"Demo Manager — {_title(dept)}",
        })
    people.append({
        "emp_id": "D500", "phone": "+919000000500", "full_name": "Demo CGM",
        "department_code": "ADMIN", "role_code": "CGM", "designation": "Demo Chief General Manager",
    })
    people.append({
        "emp_id": "D600", "phone": "+919000000600", "full_name": "Demo MD",
        "department_code": "ADMIN", "role_code": "MD", "designation": "Demo Managing Director",
    })
    return people


async def main() -> None:
    from app.security import hash_password

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    passwords: dict[str, str] = {}
    created, updated = 0, 0
    async with sm() as session:
        for spec in cast():
            emp = (
                await session.execute(select(Employee).where(Employee.phone == spec["phone"]))
            ).scalar_one_or_none()
            if emp is None:
                emp = Employee(
                    **spec, language_pref="en", shift_swap_eligible=True,
                    onboarding_status="approved", is_active=True, is_demo=True,
                )
                session.add(emp)
                await session.flush()
                session.add(ShiftAssignment(
                    employee_id=emp.id, shift_code="GEN",
                    effective_date=BASELINE_DATE, source="baseline",
                ))
                created += 1
            else:
                for k, v in spec.items():
                    setattr(emp, k, v)
                emp.is_demo = True
                emp.is_active = True
                emp.onboarding_status = "approved"
                updated += 1
            if spec["role_code"] in ("CGM", "MD"):
                pw = f"Demo@{secrets.randbelow(9000) + 1000}"
                emp.password_hash = hash_password(pw)
                emp.must_change_password = False
                passwords[spec["full_name"]] = pw
        await session.commit()
    await engine.dispose()

    print(f"Demo cast seeded: {created} created, {updated} updated")
    print(f"{'Name':<28} {'Phone':<15} {'Dept':<12} Role")
    for spec in cast():
        print(f"{spec['full_name']:<28} {spec['phone']:<15} {spec['department_code']:<12} {spec['role_code']}")
    print("\nDashboard passwords (temp):")
    for name, pw in passwords.items():
        print(f"  {name}: {pw}")


if __name__ == "__main__":
    asyncio.run(main())
