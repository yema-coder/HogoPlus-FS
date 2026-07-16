import hashlib
import logging
import os
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
from app.otp import NotConfigured, SMSDeliveryError, get_otp_sender
from app.redis_client import redis_client
from app.schemas import (
    ChangePasswordIn,
    PasswordLoginIn,
    RefreshIn,
    RegisterIn,
    SendOtpIn,
    UpdateMeIn,
    VerifyOtpIn,
)
from app.security import (
    create_registration_token,
    create_token_pair,
    decode_token,
    employee_profile,
    get_access_or_registration_payload,
    get_current_employee,
    hash_password,
    verify_password,
)
from app.shift_logic import now_ist

logger = logging.getLogger("hogo.auth")
router = APIRouter(tags=["auth"])

OTP_TTL_SECONDS = 300
SEND_WINDOW_SECONDS = 600
MAX_SENDS_PER_WINDOW = 3
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 1800


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
    except SMSDeliveryError as exc:
        raise HTTPException(status_code=502, detail=f"SMS delivery failed: {exc}")
    return {"message": "OTP sent", "otp_mode": settings.otp_mode, "expires_in": OTP_TTL_SECONDS}


@router.post("/auth/verify-otp")
async def verify_otp(body: VerifyOtpIn, session: AsyncSession = Depends(get_session)):
    phone, otp = body.phone, body.otp
    if await redis_client.exists(f"otp:lock:{phone}"):
        raise HTTPException(status_code=429, detail="Too many wrong attempts. Locked for 30 minutes.")

    stored = await redis_client.get(f"otp:code:{phone}")
    employee = (
        await session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one_or_none()
    # DEMO_OTP shortcut requires ALL of: DEMO_OTP_ENABLED, the phone explicitly listed
    # in DEMO_OTP_WHITELIST, and an existing employee row. It can never be used for
    # unknown phones or non-whitelisted seeded numbers.
    demo_ok = (
        settings.demo_otp_enabled
        and otp == settings.demo_otp
        and employee is not None
        and phone in settings.demo_otp_whitelist_set
    )
    if not ((stored and _hash(otp) == stored) or demo_ok):
        fails = await redis_client.incr(f"otp:fail:{phone}")
        if fails == 1:
            await redis_client.expire(f"otp:fail:{phone}", LOCKOUT_SECONDS)
        if fails >= LOCKOUT_THRESHOLD:
            await redis_client.setex(f"otp:lock:{phone}", LOCKOUT_SECONDS, "1")
            raise HTTPException(status_code=429, detail="Too many wrong attempts. Locked for 30 minutes.")
        raise HTTPException(status_code=401, detail=f"Invalid OTP. {LOCKOUT_THRESHOLD - fails} attempts left.")

    await redis_client.delete(f"otp:code:{phone}", f"otp:fail:{phone}")

    if employee is None:
        # unknown phone — issue a 15-min registration token for self-registration
        return {"is_new": True, "registration_token": create_registration_token(phone)}
    if not employee.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated. Contact Time Office.")

    await write_audit(session, employee.id, "auth.login", "employee", str(employee.id), {"phone": phone})
    await session.commit()
    tokens = create_token_pair(employee)
    return {**tokens, "is_new": False, "employee": employee_profile(employee)}


@router.post("/auth/register")
async def register(
    body: RegisterIn,
    token_payload: dict = Depends(get_access_or_registration_payload),
    session: AsyncSession = Depends(get_session),
):
    if token_payload["type"] == "registration" and token_payload.get("phone") != body.phone:
        raise HTTPException(status_code=403, detail="Registration token does not match this phone")

    existing = (
        await session.execute(select(Employee).where(Employee.phone == body.phone))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Phone already registered")

    # DetectFaces gate: garbage references must never enter the system.
    # Infra failures never block registration (fail open).
    if settings.aws_access_key_id and not os.environ.get("TESTING"):
        from starlette.concurrency import run_in_threadpool

        from app.aws import RekognitionUnavailable, detect_faces_count
        from app.storage import get_storage

        try:
            selfie_bytes = await run_in_threadpool(get_storage().get, body.selfie_key)
            face_count = await run_in_threadpool(detect_faces_count, selfie_bytes)
        except (RekognitionUnavailable, Exception):
            face_count = None
        if face_count == 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "no_face_detected",
                    "en": "Face not clearly visible. Please take the photo again.",
                    "hi": "चेहरा साफ नहीं दिख रहा। कृपया दोबारा फोटो लें।",
                    "mr": "चेहरा स्पष्ट दिसत नाही. कृपया पुन्हा फोटो काढा.",
                },
            )

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
        department_code=None,  # Time Office assigns department/role/emp_id on approval
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

    session.add(
        ShiftAssignment(
            employee_id=employee.id, shift_code="GEN",
            effective_date=now_ist().date(), source="baseline",
        )
    )

    # queue with Time Office: notify the TIME_OFFICE manager + CGM
    approver_ids: set = set()
    to_dept = (
        await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
    ).scalar_one_or_none()
    if to_dept and to_dept.manager_employee_id:
        approver_ids.add(to_dept.manager_employee_id)
    cgm = (
        await session.execute(
            select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if cgm:
        approver_ids.add(cgm.id)
    for approver_id in approver_ids:
        title, notif_body = template("registration_pending", f"{body.full_name} ({body.phone})")
        await dispatcher.notify(session, approver_id, "registration_pending", title, notif_body, "employee", str(employee.id))

    await write_audit(session, employee.id, "employee.register", "employee", str(employee.id), {"phone": body.phone})
    await session.commit()
    await session.refresh(employee)
    tokens = create_token_pair(employee)
    return {**tokens, "employee": employee_profile(employee)}


# ---- Password login (WEB DASHBOARD only, MD/CGM = rank <= 2). Mobile stays phone+OTP. ----

PW_MAX_ATTEMPTS = 5
PW_WINDOW_SECONDS = 15 * 60

PW_LOCKOUT_DETAIL = {
    "code": "password_login_locked",
    "en": "Too many wrong attempts. Try again after 15 minutes.",
    "hi": "बहुत बार गलत पासवर्ड। 15 मिनट बाद फिर कोशिश करें।",
    "mr": "खूप वेळा चुकीचा पासवर्ड. 15 मिनिटांनी पुन्हा प्रयत्न करा.",
}


def _pw_fail_key(emp_id: str) -> str:
    return f"pwlogin:fail:{emp_id}"


@router.post("/auth/password-login")
async def password_login(body: PasswordLoginIn, session: AsyncSession = Depends(get_session)):
    fail_key = _pw_fail_key(body.emp_id)
    fails = int(await redis_client.get(fail_key) or 0)
    if fails >= PW_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail=PW_LOCKOUT_DETAIL)

    employee = (
        await session.execute(select(Employee).where(Employee.emp_id == body.emp_id))
    ).scalar_one_or_none()

    async def _record_fail():
        count = await redis_client.incr(fail_key)
        if count == 1:
            await redis_client.expire(fail_key, PW_WINDOW_SECONDS)

    if employee is None or not employee.is_active or not employee.password_hash:
        await _record_fail()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, employee.password_hash):
        await _record_fail()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # role gate AFTER credential check but before token issue: only MD/CGM may
    # password-login, even if a password somehow got set for someone else.
    if employee.role.rank > 2:
        raise HTTPException(status_code=403, detail="Password login is for MD/CGM only")

    await redis_client.delete(fail_key)
    await write_audit(session, employee.id, "auth.password_login", "employee", str(employee.id), {})
    await session.commit()
    tokens = create_token_pair(employee)
    return {
        **tokens,
        "employee": employee_profile(employee),
        "must_change_password": employee.must_change_password,
    }


@router.post("/auth/change-password")
async def change_password(
    body: ChangePasswordIn,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    if not employee.password_hash:
        raise HTTPException(status_code=400, detail="Password login is not enabled for this account")
    if not verify_password(body.current_password, employee.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    employee.password_hash = hash_password(body.new_password)
    employee.must_change_password = False
    await write_audit(session, employee.id, "auth.password_changed", "employee", str(employee.id), {})
    await session.commit()
    await redis_client.delete(_pw_fail_key(employee.emp_id))
    return {"status": "password_changed"}


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
