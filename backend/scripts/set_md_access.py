"""Grant MD dashboard access to a phone + (re)set the shared MD password.

Idempotent, EC2-runnable (same pattern as seed_head_office_md.py). Run on the
PRODUCTION box after the code is deployed:

    docker compose exec -T api python scripts/set_md_access.py
    # custom values:
    docker compose exec -T api python scripts/set_md_access.py \
        --add-phone +919096171949 --password 'Hogo@123'

What it does, idempotently:
 1. ADDS --add-phone to settings.md_otp_phones (keeps every existing number;
    de-duplicated, sorted). That number can then OTP-login on the webdash and
    auto-elevate to the shared MD dashboard (POST /api/auth/md-elevate).
 2. FORCE-sets settings.md_password_hash = hash_password(--password). Unlike the
    original handover seed (which only set it "if not already set"), this always
    resets it — the operator explicitly asked for a known password.
 3. Ensures the --add-phone employee row is is_active + onboarding_status=approved
    so it can actually OTP-login. It does NOT create a fake row and does NOT touch
    the employee's own role/department (md-elevate only needs the phone whitelisted).
Everything is audited. Prints the final MD-access state.

NOTE: this changes DATABASE DATA, not code — it must run against the target
(production) database. Running it in the sandbox only affects the sandbox DB.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.models import Employee, FactorySettings

DEFAULT_ADD_PHONE = "+919096171949"
DEFAULT_PASSWORD = "Hogo@123"


async def apply(session: AsyncSession, add_phone: str, password: str) -> list[str]:
    from app.security import hash_password

    out: list[str] = []
    fs = (await session.execute(select(FactorySettings))).scalars().first()
    if fs is None:
        raise RuntimeError("settings row missing — base seed has not run on this DB")

    # 1) add the phone to the MD OTP whitelist (keep every existing number) -----
    phones = [p.strip() for p in (fs.md_otp_phones or "").split(",") if p.strip()]
    before = ",".join(phones)
    if add_phone not in phones:
        phones.append(add_phone)
        fs.md_otp_phones = ",".join(sorted(set(phones)))
        await write_audit(
            session, None, "admin.md_otp_phone_added", "settings", None,
            {"added": add_phone, "before": before, "after": fs.md_otp_phones,
             "source": "set_md_access.py"},
            is_demo=False,
        )
        out.append(f"md_otp_phones: added {add_phone}")
    else:
        fs.md_otp_phones = ",".join(sorted(set(phones)))
        out.append(f"md_otp_phones: {add_phone} already present — no change")

    # 2) force-reset the shared MD dashboard password ---------------------------
    fs.md_password_hash = hash_password(password)
    await write_audit(
        session, None, "admin.md_password_changed", "settings", None,
        {"source": "set_md_access.py", "forced": True}, is_demo=False,
    )
    out.append(f"md_password_hash: reset to the supplied password")

    # 3) make sure the phone can actually OTP-login -----------------------------
    emp = (
        await session.execute(select(Employee).where(Employee.phone == add_phone))
    ).scalar_one_or_none()
    if emp is None:
        out.append(f"WARNING: no employee row for {add_phone} — it CANNOT OTP-login "
                   f"until an employee with this phone exists (create it in the webdash).")
    else:
        changed = {}
        if not emp.is_active:
            changed["is_active"] = {"old": emp.is_active, "new": True}
            emp.is_active = True
        if emp.onboarding_status != "approved":
            changed["onboarding_status"] = {"old": emp.onboarding_status, "new": "approved"}
            emp.onboarding_status = "approved"
        if changed:
            await write_audit(
                session, None, "employee.updated", "employee", str(emp.id),
                {**changed, "source": "set_md_access.py"}, is_demo=False,
            )
            out.append(f"employee {emp.emp_id} ({add_phone}): activated/approved for login")
        else:
            out.append(f"employee {emp.emp_id} ({add_phone}): already active + approved")

    await session.commit()
    return out


async def main() -> None:
    from app.database import SessionLocal, engine

    parser = argparse.ArgumentParser()
    parser.add_argument("--add-phone", default=DEFAULT_ADD_PHONE,
                        help="phone (+91XXXXXXXXXX) to grant MD-OTP access")
    parser.add_argument("--password", default=DEFAULT_PASSWORD,
                        help="new shared MD dashboard password (password-only tab)")
    args = parser.parse_args()

    async with SessionLocal() as session:
        for line in await apply(session, args.add_phone, args.password):
            print(line)

        print("\n=== FINAL MD-ACCESS STATE ===")
        fs = (await session.execute(select(FactorySettings))).scalars().first()
        print(f"  MD password set: {'YES' if fs.md_password_hash else 'NO'}")
        print(f"  MD OTP numbers:  {fs.md_otp_phones}")
        emp = (await session.execute(
            select(Employee).where(Employee.phone == args.add_phone)
        )).scalar_one_or_none()
        if emp:
            print(f"  {args.add_phone}: emp_id={emp.emp_id} role={emp.role_code} "
                  f"active={emp.is_active} onboarding={emp.onboarding_status}")
        else:
            print(f"  {args.add_phone}: NO employee row (cannot OTP-login yet)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
