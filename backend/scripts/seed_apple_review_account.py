"""APPLE REVIEW DEMO ACCOUNT — one idempotent data script (v1.0.24).

Run on the EC2 box:
    docker compose exec -T api python scripts/seed_apple_review_account.py

Creates (or repairs) ONE demo account for the Apple App Store review team:
    phone  +919123456789   (reviewer types 9123456789 in the app)
    OTP    fixed demo OTP  (no SMS is ever sent — is_demo path)

    NOTE: the requested 1234567890 is impossible — both the app and the API
    enforce the Indian mobile pattern +91[6-9]XXXXXXXXX (must start 6-9).
    9123456789 is the closest memorable compliant number: 9 + 123456789.

    role   CGM (rank 2)    → the widest single-login surface: home dashboard,
                             ALL departments (Departments tile), Approvals,
                             Employees directory + add-wizard, Announce,
                             Sahayak AI, alerts, reports, ID card
    dept   HEAD_OFFICE     → beacon_exempt + geofence_exempt, so PUNCH-IN
                             WORKS FROM CUPERTINO (no beacon, any GPS)
    is_demo TRUE           → demo data separation: the reviewer never touches
                             real factory data, and send-otp short-circuits
                             before any SMS gateway call.

PREREQUISITES ON PROD (.env of the api container — script verifies and warns):
    DEMO_OTP_ENABLED=true
    DEMO_OTP=123456
NOTE: one login can hold only ONE role. CGM is the superset view. If Apple asks
for a worker-level login too, the demo cast (+919000000009 etc.) already works
with the same fixed OTP.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.models import Department, Employee, ShiftAssignment

APPLE_PHONE = "+919123456789"
APPLE_EMP_ID = "APPLE"
APPLE_NAME = "Apple Review"
APPLE_ROLE = "CGM"
PREFERRED_DEPT = "HEAD_OFFICE"   # falls back to ADMIN if the dept doesn't exist yet
FALLBACK_DEPT = "ADMIN"


async def apply(session: AsyncSession) -> list[str]:
    from app.shift_logic import now_ist

    log: list[str] = []

    dept = (
        await session.execute(select(Department).where(Department.code == PREFERRED_DEPT))
    ).scalar_one_or_none()
    dept_code = PREFERRED_DEPT if dept is not None else FALLBACK_DEPT
    if dept is None:
        log.append(f"! {PREFERRED_DEPT} missing (run seed_head_office_md.py first) — using {FALLBACK_DEPT}")

    emp = (
        await session.execute(select(Employee).where(Employee.phone == APPLE_PHONE))
    ).scalar_one_or_none()
    if emp is None:
        # emp_id collision guard (idempotent even if someone reused "APPLE")
        clash = (
            await session.execute(select(Employee).where(Employee.emp_id == APPLE_EMP_ID))
        ).scalar_one_or_none()
        emp_id = APPLE_EMP_ID if clash is None else "APPLE2"
        emp = Employee(
            emp_id=emp_id, full_name=APPLE_NAME, phone=APPLE_PHONE,
            department_code=dept_code, designation="CGM", role_code=APPLE_ROLE,
            language_pref="en", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True, is_demo=True,
        )
        session.add(emp)
        await session.flush()
        session.add(ShiftAssignment(
            employee_id=emp.id, shift_code="GEN", effective_date=now_ist().date(),
        ))
        await write_audit(
            session, emp.id, "employee.created", "employee", str(emp.id),
            {"source": "seed_apple_review_account"}, is_demo=True,
        )
        log.append(f"+ created {emp_id} | {APPLE_NAME} | {APPLE_PHONE} | {APPLE_ROLE} | {dept_code} | is_demo=True")
    else:
        # repair to the expected state — never duplicates
        changed = []
        for attr, want in (
            ("full_name", APPLE_NAME), ("role_code", APPLE_ROLE), ("designation", "CGM"),
            ("department_code", dept_code), ("language_pref", "en"),
            ("onboarding_status", "approved"), ("is_active", True), ("is_demo", True),
        ):
            if getattr(emp, attr) != want:
                setattr(emp, attr, want)
                changed.append(attr)
        has_shift = (
            await session.execute(
                select(ShiftAssignment).where(ShiftAssignment.employee_id == emp.id)
            )
        ).scalars().first()
        if has_shift is None:
            session.add(ShiftAssignment(
                employee_id=emp.id, shift_code="GEN", effective_date=now_ist().date(),
            ))
            changed.append("shift(GEN)")
        if changed:
            await write_audit(
                session, emp.id, "employee.updated", "employee", str(emp.id),
                {"source": "seed_apple_review_account", "fields": changed}, is_demo=True,
            )
            log.append(f"~ repaired {emp.emp_id}: {', '.join(changed)}")
        else:
            log.append(f"= {emp.emp_id} already in the expected state — nothing to do")

    await session.commit()
    return log


async def main() -> None:
    from app.config import settings
    from app.database import SessionLocal, engine

    async with SessionLocal() as session:
        for line in await apply(session):
            print(line)

        print("\n=== APPLE REVIEW ACCOUNT — FINAL ROW ===")
        e = (
            await session.execute(select(Employee).where(Employee.phone == APPLE_PHONE))
        ).scalar_one()
        print(f"  {e.emp_id} | {e.full_name} | {e.phone} | role={e.role_code} | "
              f"dept={e.department_code} | active={e.is_active} | demo={e.is_demo} | "
              f"status={e.onboarding_status}")

        print("\n=== ENV CHECK (must both hold on PROD for the fixed OTP) ===")
        print(f"  DEMO_OTP_ENABLED = {settings.demo_otp_enabled}"
              + ("" if settings.demo_otp_enabled else "   <<< FIX: set true in .env + restart api"))
        print(f"  DEMO_OTP         = {settings.demo_otp}"
              + ("" if settings.demo_otp == "123456" else "   <<< NOTE: reviewers were told 123456"))
        print("\nApp Store Connect review notes to paste:")
        print("  Phone: 9123456789   OTP: 123456 (demo account, no SMS is sent)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
