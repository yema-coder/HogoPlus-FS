import hashlib
import logging
import secrets
import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Integer as SAInteger

from app.audit import write_audit
from app.config import settings
from app.database import get_session
from app.models import Department, Employee, OtpAttempt, ShiftAssignment
from app.notify import dispatcher, template
from app.otp import NotConfigured, get_otp_sender
from app.redis_client import redis_client
from app.schemas import RefreshIn, RegisterIn, SendOtpIn, UpdateMeIn, VerifyOtpIn
from app.security import (
    create_token_pair,
    decode_token,
    employee_profile,
    get_current_employee,
)
from app.shift_logic import SHIFT_A_DEPARTMENTS, now_ist

logger = logging.getLogger("hogo.auth")
router = APIRouter(tags=["auth"])

OTP_TTL_SECONDS = 300
SEND_WINDOW_SECONDS = 600
MAX_SENDS_PER_WINDOW = 3
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 1800
REGISTER_WINDOW_SECONDS = 900


def _hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


@router.post("/auth/send-otp")
async def send_otp(body: SendOtpIn, session: AsyncSession = Depends(get_session)):
    phone = body.phone
    rate_key = f"otp:send:{phone}"
    count = await redis_client.incr(rate_key)
    if count == 1:
        await redis_client.expire(rate_key, SEND_WINDOW_SECONDS)
    if count > MAX_SENDS_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many OTP requests. Try again in 10 minutes.")

    otp = f"{secrets.randbelow(10**6):06d}"
    await redis_client.setex(f"otp:code:{phone}", OTP_TTL_SECONDS, _hash(otp))
    session.add(OtpAttempt(phone=phone, purpose="login"))
    await session.commit()
    try:
        await get_otp_sender().send(phone, otp)
    except NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"message": "OTP sent", "otp_mode": settings.otp_mode, "expires_in": OTP_TTL_SECONDS}


@router.post("/auth/verify-otp")
async def verify_otp(body: VerifyOtpIn, session: AsyncSession = Depends(get_session)):
    phone, otp = body.phone, body.otp
    if await redis_client.exists(f"otp:lock:{phone}"):
        raise HTTPException(status_code=429, detail="Too many wrong attempts. Locked for 30 minutes.")

    stored = await redis_client.get(f"otp:code:{phone}")
    demo_ok = settings.demo_otp_enabled and otp == settings.demo_otp
    if not ((stored and _hash(otp) == stored) or demo_ok):
        fails = await redis_client.incr(f"otp:fail:{phone}")
        if fails == 1:
            await redis_client.expire(f"otp:fail:{phone}", LOCKOUT_SECONDS)
        if fails >= LOCKOUT_THRESHOLD:
            await redis_client.setex(f"otp:lock:{phone}", LOCKOUT_SECONDS, "1")
            raise HTTPException(status_code=429, detail="Too many wrong attempts. Locked for 30 minutes.")
        raise HTTPException(status_code=401, detail=f"Invalid OTP. {LOCKOUT_THRESHOLD - fails} attempts left.")

    await redis_client.delete(f"otp:code:{phone}", f"otp:fail:{phone}")

    employee = (
        await session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one_or_none()
    if employee is None:
        # unknown phone — allow self-registration within a window
        await redis_client.setex(f"otp:verified:{phone}", REGISTER_WINDOW_SECONDS, "1")
        return {"is_new": True}
    if not employee.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated. Contact Time Office.")

    await write_audit(session, employee.id, "auth.login", "employee", str(employee.id), {"phone": phone})
    await session.commit()
    tokens = create_token_pair(employee)
    return {**tokens, "is_new": False, "employee": employee_profile(employee)}


@router.post("/auth/register")
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)):
    if not await redis_client.get(f"otp:verified:{body.phone}"):
        raise HTTPException(status_code=403, detail="Phone not OTP-verified. Verify OTP first.")

    existing = (
        await session.execute(select(Employee).where(Employee.phone == body.phone))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Phone already registered")

    dept = (
        await session.execute(select(Department).where(Department.code == body.department_code))
    ).scalar_one_or_none()
    if dept is None or not dept.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    max_num = (
        await session.execute(
            select(func.max(cast(Employee.emp_id, SAInteger))).where(Employee.emp_id.op("~")(r"^\d+$"))
        )
    ).scalar() or 0
    emp_id = f"{max_num + 1:04d}"

    employee = Employee(
        emp_id=emp_id,
        full_name=body.full_name,
        phone=body.phone,
        department_code=body.department_code,
        designation="Self Registered Worker",
        role_code="Worker",
        language_pref="mr",
        shift_swap_eligible=True,
        onboarding_status="pending_approval",
        selfie_url=f"/api/files/{body.selfie_key}",
        is_active=True,
    )
    session.add(employee)
    await session.flush()

    shift_code = "A" if body.department_code in SHIFT_A_DEPARTMENTS else "GEN"
    session.add(
        ShiftAssignment(
            employee_id=employee.id, shift_code=shift_code,
            effective_date=now_ist().date(), source="baseline",
        )
    )

    # notify dept manager (or CGM) about the pending registration
    approver_id = dept.manager_employee_id
    if approver_id is None:
        cgm = (
            await session.execute(
                select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        approver_id = cgm.id if cgm else None
    if approver_id:
        title, notif_body = template("registration_pending", f"{body.full_name} ({body.phone})")
        await dispatcher.notify(session, approver_id, "registration_pending", title, notif_body, "employee", str(employee.id))

    await write_audit(session, employee.id, "employee.register", "employee", str(employee.id), {"phone": body.phone})
    await session.commit()
    await session.refresh(employee)
    await redis_client.delete(f"otp:verified:{body.phone}")
    tokens = create_token_pair(employee)
    return {**tokens, "employee": employee_profile(employee)}


@router.post("/auth/refresh")
async def refresh(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    payload = decode_token(body.refresh_token, "refresh")
    try:
        emp_uuid = uuid_mod.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    employee = await session.get(Employee, emp_uuid)
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=401, detail="Employee not found or inactive")
    return create_token_pair(employee)


@router.get("/auth/me")
async def me(employee: Employee = Depends(get_current_employee)):
    return employee_profile(employee)


@router.patch("/employees/me")
async def update_me(
    body: UpdateMeIn,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    if body.language_pref is not None:
        employee.language_pref = body.language_pref
    if body.expo_push_token is not None:
        employee.expo_push_token = body.expo_push_token
    await session.commit()
    await session.refresh(employee)
    return employee_profile(employee)
