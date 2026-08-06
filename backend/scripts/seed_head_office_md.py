"""HEAD OFFICE + MD ACCESS REDESIGN — one idempotent data script (v1.0.24).

Run on the EC2 box AFTER `alembic upgrade head`:
    docker compose exec -T api python scripts/seed_head_office_md.py
    docker compose exec -T api python scripts/seed_head_office_md.py --name "Real Name"

Does, idempotently:
 1. HEAD_OFFICE department (Pune, remote): beacon_exempt + geofence_exempt +
    can_add_employees all ON. TIME_OFFICE keeps can_add_employees ON.
 2. Head Office manager +919511738318 (role Manager, emp_id from the auto-suggest
    pool, HOD of HEAD_OFFICE). Rename anytime via webdash Employees editor.
 3. Shared MD dashboard account: emp_id "MD", name "Prasad Sugar Mill", role MD,
    NO phone, NO personal password (the MD password lives in settings).
 4. settings.md_password_hash = Hogo@123 ONLY if not already set (a changed
    password is never reset); settings.md_otp_phones = the two allowed numbers.
 5. REVOKES MD access from +919096171949 and +919561722986 → role Manager,
    personal passwords cleared. Everything audited.
Prints the final MD-access state.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.models import Department, Employee, FactorySettings, ShiftAssignment

# ============================================================================
# >>> EDIT BEFORE RUNNING ON EC2 <<<
#
# HO_MANAGER_NAME   — the REAL full name of the Head Office manager
#                     (+91 9511738318). Placeholder below until you set it.
# HO_MANAGER_EMP_ID — None = auto-pick the next free numeric emp_id (e.g. 0057).
#                     Set a string like "0101" to force a specific emp_id.
#                     Only used when the row is being CREATED (never renumbers
#                     an existing employee).
#
# You can also override the name at run time without editing the file:
#     python scripts/seed_head_office_md.py --name "Real Name"
# ============================================================================
HO_MANAGER_NAME = "Mahesh Makne"          # real name (confirmed by user)
HO_MANAGER_EMP_ID = None                  # <<< EDIT: e.g. "0101", or None = auto

# --- fixed batch constants (do not edit) ------------------------------------
HO_CODE = "HEAD_OFFICE"
HO_MANAGER_PHONE = "+919511738318"
MD_OTP_PHONES = "+919511738318,+918483029039"
DEMOTE_PHONES = ["+919096171949", "+919561722986"]
SHARED_MD_EMP_ID = "MD"
INITIAL_MD_PASSWORD = "Hogo@123"


async def apply(session: AsyncSession, ho_manager_name: str = HO_MANAGER_NAME) -> list[str]:
    from app.security import hash_password
    from app.shift_logic import now_ist

    out: list[str] = []

    # 1) HEAD_OFFICE department + policy flags -------------------------------
    dept = (
        await session.execute(select(Department).where(Department.code == HO_CODE))
    ).scalar_one_or_none()
    if dept is None:
        dept = Department(
            code=HO_CODE, name_en="Head Office", name_hi="हेड ऑफ़िस", name_mr="हेड ऑफिस",
            is_active=True,
        )
        session.add(dept)
        await session.flush()
        out.append("HEAD_OFFICE department created")
    dept.beacon_exempt = True
    dept.geofence_exempt = True
    dept.can_add_employees = True
    to = (
        await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
    ).scalar_one_or_none()
    if to is not None:
        to.can_add_employees = True

    # 2) Head Office manager --------------------------------------------------
    mgr = (
        await session.execute(select(Employee).where(Employee.phone == HO_MANAGER_PHONE))
    ).scalar_one_or_none()
    if mgr is None:
        if HO_MANAGER_EMP_ID:
            new_emp_id = HO_MANAGER_EMP_ID
        else:
            next_id = (
                await session.execute(
                    sa_text(r"SELECT COALESCE(MAX(emp_id::int), 0) FROM employees WHERE emp_id ~ '^\d{1,4}$'")
                )
            ).scalar() or 0
            new_emp_id = f"{next_id + 1:04d}"
        mgr = Employee(
            emp_id=new_emp_id, full_name=ho_manager_name, phone=HO_MANAGER_PHONE,
            department_code=HO_CODE, designation="Manager", role_code="Manager",
            language_pref="mr", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True, is_demo=False,
        )
        session.add(mgr)
        await session.flush()
        session.add(ShiftAssignment(
            employee_id=mgr.id, shift_code="GEN", effective_date=now_ist().date(),
        ))
        await write_audit(
            session, None, "employee.created", "employee", str(mgr.id),
            {"source": "seed_head_office_md.py", "emp_id": mgr.emp_id, "phone": HO_MANAGER_PHONE},
            is_demo=False,
        )
        out.append(f"HO manager created: {mgr.emp_id} ({HO_MANAGER_PHONE})")
    else:
        if mgr.department_code != HO_CODE or mgr.role_code != "Manager":
            await write_audit(
                session, None, "employee.updated", "employee", str(mgr.id),
                {"department_code": {"old": mgr.department_code, "new": HO_CODE},
                 "role_code": {"old": mgr.role_code, "new": "Manager"},
                 "source": "seed_head_office_md.py"},
                is_demo=False,
            )
            mgr.department_code = HO_CODE
            mgr.role_code = "Manager"
        mgr.is_active = True
        mgr.onboarding_status = "approved"
    dept.manager_employee_id = mgr.id  # HOD → gets the add-employee capability

    # 3) Shared MD dashboard account ------------------------------------------
    md = (
        await session.execute(select(Employee).where(Employee.emp_id == SHARED_MD_EMP_ID))
    ).scalar_one_or_none()
    if md is None:
        md = Employee(
            emp_id=SHARED_MD_EMP_ID, full_name="Prasad Sugar Mill", phone=None,
            department_code="ADMIN", designation="MD", role_code="MD",
            language_pref="mr", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True, is_demo=False,
        )
        session.add(md)
        await session.flush()
        await write_audit(
            session, None, "employee.created", "employee", str(md.id),
            {"source": "seed_head_office_md.py", "shared_md_account": True}, is_demo=False,
        )
        out.append("Shared MD account created (emp_id=MD, no phone, no personal password)")
    md.role_code = "MD"
    md.is_active = True
    md.password_hash = None  # the MD password lives in settings, NOT on the account
    md.must_change_password = False

    # 4) Settings: MD password + OTP whitelist --------------------------------
    fs = (await session.execute(select(FactorySettings))).scalars().first()
    if fs is None:
        raise RuntimeError("settings row missing — base seed has not run")
    if not fs.md_password_hash:
        fs.md_password_hash = hash_password(INITIAL_MD_PASSWORD)
        await write_audit(session, None, "admin.md_password_changed", "settings", None,
                          {"source": "seed_head_office_md.py", "initial": True}, is_demo=False)
        out.append(f"MD password set to initial {INITIAL_MD_PASSWORD} (change it from Admin)")
    else:
        out.append("MD password already set — NOT touched")
    fs.md_otp_phones = MD_OTP_PHONES

    # 5) Revoke MD access from the two earlier handover numbers ---------------
    for phone in DEMOTE_PHONES:
        e = (
            await session.execute(select(Employee).where(Employee.phone == phone))
        ).scalar_one_or_none()
        if e is None:
            out.append(f"{phone}: no row — nothing to demote")
            continue
        changes: dict = {}
        if e.role_code == "MD":
            changes["role_code"] = {"old": "MD", "new": "Manager"}
            e.role_code = "Manager"
        if e.password_hash is not None:
            changes["password"] = {"new": "cleared (password login revoked)"}
            e.password_hash = None
            e.must_change_password = False
        if changes:
            await write_audit(
                session, None, "employee.md_access_revoked", "employee", str(e.id),
                {**changes, "source": "seed_head_office_md.py"}, is_demo=False,
            )
            out.append(f"{e.emp_id} {phone}: MD access revoked → role Manager")
        else:
            out.append(f"{e.emp_id} {phone}: already Manager, no password — no change")

    await session.commit()
    return out


async def main() -> None:
    from app.database import SessionLocal, engine

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default=HO_MANAGER_NAME,
                        help="Full name for the +919511738318 Head Office manager")
    args = parser.parse_args()

    async with SessionLocal() as session:
        for line in await apply(session, args.name):
            print(line)

        print("\n=== FINAL MD-ACCESS STATE ===")
        fs = (await session.execute(select(FactorySettings))).scalars().first()
        print(f"  MD password set: {'YES' if fs.md_password_hash else 'NO'}")
        print(f"  MD OTP numbers:  {fs.md_otp_phones}")
        for emp_id in (SHARED_MD_EMP_ID,):
            e = (await session.execute(select(Employee).where(Employee.emp_id == emp_id))).scalar_one_or_none()
            if e:
                print(f"  Shared account:  {e.emp_id} | {e.full_name} | role={e.role_code} | phone={e.phone} | personal_password={'SET' if e.password_hash else 'none'}")
        ho = (await session.execute(select(Employee).where(Employee.phone == HO_MANAGER_PHONE))).scalar_one_or_none()
        if ho:
            print(f"  HO manager:      {ho.emp_id} | {ho.full_name} | {ho.phone} | role={ho.role_code} | dept={ho.department_code}")
        print("  Demoted rows:")
        for phone in DEMOTE_PHONES:
            e = (await session.execute(select(Employee).where(Employee.phone == phone))).scalar_one_or_none()
            if e:
                print(f"    {e.emp_id} | {e.full_name} | {phone} | role={e.role_code} | password={'SET' if e.password_hash else 'none'}")
        d = (await session.execute(select(Department).where(Department.code == HO_CODE))).scalar_one_or_none()
        if d:
            print(f"  HEAD_OFFICE: beacon_exempt={d.beacon_exempt} geofence_exempt={d.geofence_exempt} can_add_employees={d.can_add_employees}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
