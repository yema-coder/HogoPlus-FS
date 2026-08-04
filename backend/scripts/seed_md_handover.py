"""MD HANDOVER (one-time, idempotent): link the two owner-provided phone numbers
to the MD role with a TEMPORARY dashboard password (must change on first login).

Run on the EC2 box:
    docker compose exec -T api python scripts/seed_md_handover.py

Safe to run repeatedly:
- role/status fixes re-apply only when needed
- the temp password is NEVER re-applied once the owner has changed it
  (must_change_password=False ⇒ password untouched)
- touches ONLY the two listed phones; prints the CGM 0001 row for confirmation
- every change lands in the audit log (action=employee.md_handover)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.models import Employee

MD_PHONES = ["+919096171949", "+919561722986"]
TEMP_PASSWORD = "Hogo@123"


async def apply_md_handover(session: AsyncSession) -> list[str]:
    """Core, importable for tests. Returns human-readable change lines."""
    from app.security import hash_password

    out: list[str] = []
    for phone in MD_PHONES:
        emp = (
            await session.execute(select(Employee).where(Employee.phone == phone))
        ).scalar_one_or_none()
        if emp is None:
            out.append(f"!! {phone}: NO employee row found — nothing changed")
            continue
        changes: dict = {}
        if emp.role_code != "MD":
            changes["role_code"] = {"old": emp.role_code, "new": "MD"}
            emp.role_code = "MD"
        if not emp.is_active:
            changes["is_active"] = {"old": False, "new": True}
            emp.is_active = True
        if emp.onboarding_status != "approved":
            changes["onboarding_status"] = {"old": emp.onboarding_status, "new": "approved"}
            emp.onboarding_status = "approved"
        # temp password: set on first run / while still unchanged. NEVER overwrite
        # a password the owner has already changed (must_change_password=False).
        if emp.password_hash is None or emp.must_change_password:
            emp.password_hash = hash_password(TEMP_PASSWORD)
            emp.must_change_password = True
            changes["password"] = {"new": "temporary set — forced change on first login"}
        if changes:
            await write_audit(
                session, None, "employee.md_handover", "employee", str(emp.id),
                {**changes, "source": "seed_md_handover.py"}, is_demo=False,
            )
            out.append(f"{emp.emp_id} {phone}: " + ", ".join(changes.keys()))
        else:
            out.append(f"{emp.emp_id} {phone}: already correct — no change")
    await session.commit()
    return out


async def main() -> None:
    from app.database import SessionLocal, engine

    async with SessionLocal() as session:
        for line in await apply_md_handover(session):
            print(line)
        print("\n=== MD accounts (after) ===")
        rows = (
            await session.execute(
                select(Employee).where(Employee.phone.in_(MD_PHONES)).order_by(Employee.emp_id)
            )
        ).scalars().all()
        for e in rows:
            print(
                f"  emp_id={e.emp_id} | {e.full_name} | {e.phone} | role={e.role_code} | "
                f"dept={e.department_code} | active={e.is_active} | "
                f"must_change_password={e.must_change_password}"
            )
        owner = (
            await session.execute(select(Employee).where(Employee.emp_id == "0001"))
        ).scalar_one_or_none()
        if owner:
            print("=== Owner account (UNTOUCHED) ===")
            print(
                f"  emp_id={owner.emp_id} | {owner.full_name} | {owner.phone} | "
                f"role={owner.role_code} | dept={owner.department_code} | active={owner.is_active} | "
                f"must_change_password={owner.must_change_password}"
            )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
