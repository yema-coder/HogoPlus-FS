import hashlib
import logging
import os
import secrets
import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Integer as SAInteger

from app.audit import write_audit
from app.config import settings
from app.database import get_session
from app.models import AppVersion, Department, Employee, FactorySettings, OtpAttempt, ShiftAssignment
from app.notify import dispatcher, template
from app.otp import NotConfigured, SMSDeliveryError, get_otp_sender
from app.redis_client import redis_client
from app.routers.attendance import _haversine_m
from app.schemas import (
    ChangePasswordIn,
    FaceEnrollIn,
    MdLoginIn,
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
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 1800


def _hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _rate_limit_detail(wait_seconds: int) -> dict:
    """429 body always carries the remaining wait so the app can show it."""
    wait_seconds = max(int(wait_seconds), 1)
    return {
        "code": "otp_rate_limited",
        "retry_after_seconds": wait_seconds,
        "en": f"Please wait {wait_seconds} seconds before requesting another OTP.",
        "hi": f"कृपया अगला OTP मांगने से पहले {wait_seconds} सेकंड प्रतीक्षा करें।",
        "mr": f"कृपया पुढील OTP मागण्यापूर्वी {wait_seconds} सेकंद थांबा.",
    }


@router.post("/auth/send-otp")
async def send_otp(body: SendOtpIn, session: AsyncSession = Depends(get_session)):
    phone = body.phone
    employee = (
        await session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one_or_none()

    # Demo showcase accounts never receive real SMS — they log in with the fixed demo OTP.
    if employee is not None and employee.is_demo:
        return {"message": "OTP sent", "otp_mode": "demo_account", "expires_in": OTP_TTL_SECONDS}

    # Registration guard (contest window): unknown numbers get a friendly trilingual
    # block and NO SMS is sent — protects SMS credits.
    if employee is None and not settings.allow_new_registration:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "registration_closed",
                "en": "New registration is temporarily closed. Please contact the Time Office.",
                "hi": "नया पंजीकरण अभी बंद है। कृपया टाइम ऑफिस से संपर्क करें।",
                "mr": "नवीन नोंदणी सध्या बंद आहे. कृपया टाइम ऑफिसशी संपर्क साधा.",
            },
        )

    # Prompt 21 Bug-1 rate limit: OTP_MAX_PER_WINDOW sends per OTP_WINDOW_MINUTES,
    # with an OTP_RESEND_COOLDOWN_SECONDS gap between sends — all .env-configurable.
    cooldown = settings.otp_resend_cooldown_seconds
    if cooldown > 0:
        cd_ttl = await redis_client.ttl(f"otp:cooldown:{phone}")
        if cd_ttl and cd_ttl > 0:
            raise HTTPException(status_code=429, detail=_rate_limit_detail(cd_ttl))
    window_seconds = settings.otp_window_minutes * 60
    rate_key = f"otp:send:{phone}"
    count = await redis_client.incr(rate_key)
    if count == 1:
        await redis_client.expire(rate_key, window_seconds)
    if count > settings.otp_max_per_window:
        window_ttl = await redis_client.ttl(rate_key)
        raise HTTPException(
            status_code=429,
            detail=_rate_limit_detail(window_ttl if window_ttl and window_ttl > 0 else window_seconds),
        )

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
    if cooldown > 0:
        await redis_client.setex(f"otp:cooldown:{phone}", cooldown, "1")
    return {
        "message": "OTP sent",
        "otp_mode": settings.otp_mode,
        "expires_in": OTP_TTL_SECONDS,
        "resend_after": cooldown,
    }


@router.post("/auth/verify-otp")
async def verify_otp(body: VerifyOtpIn, session: AsyncSession = Depends(get_session)):
    phone, otp = body.phone, body.otp
    if await redis_client.exists(f"otp:lock:{phone}"):
        raise HTTPException(status_code=429, detail="Too many wrong attempts. Locked for 30 minutes.")

    stored = await redis_client.get(f"otp:code:{phone}")
    employee = (
        await session.execute(select(Employee).where(Employee.phone == phone))
    ).scalar_one_or_none()
    # DEMO_OTP shortcut requires ALL of: DEMO_OTP_ENABLED, an existing employee row,
    # and EITHER employee.is_demo=true (demo showcase cast) OR the phone explicitly
    # listed in DEMO_OTP_WHITELIST (real admin numbers). Real non-whitelisted
    # employees and unknown phones always need a real SMS OTP.
    demo_ok = (
        settings.demo_otp_enabled
        and otp == settings.demo_otp
        and employee is not None
        and (employee.is_demo or phone in settings.demo_otp_whitelist_set)
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
    face_count: int | None = None
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
            # 4-digit pool only — legacy garbage ids (300312 etc) must not drive this
            select(func.max(cast(Employee.emp_id, SAInteger))).where(Employee.emp_id.op("~")(r"^\d{1,4}$"))
        )
    ).scalar() or 0
    emp_id = f"{max_num + 1:04d}"

    # v1.0.20: was the phone inside the factory geofence at registration time?
    reg_inside: bool | None = None
    if body.lat is not None and body.lng is not None:
        fs = (await session.execute(select(FactorySettings))).scalars().first()
        if fs and fs.factory_lat is not None and fs.factory_lng is not None:
            reg_inside = (
                _haversine_m(body.lat, body.lng, fs.factory_lat, fs.factory_lng)
                <= (fs.radius_meters or 500)
            )

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
        reg_lat=body.lat,
        reg_lng=body.lng,
        reg_address=body.address,
        reg_zone=body.zone,
        reg_inside_geofence=reg_inside,
        reg_device=body.device,
        reg_app_version=body.app_version,
        reg_face_count=face_count,
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
            select(Employee).where(
                Employee.role_code == "CGM", Employee.is_active.is_(True),
                Employee.is_demo.is_(False),
            ).limit(1)
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


# ---- v1.0.24 MD ACCESS REDESIGN -------------------------------------------------
# The MD dashboard opens with ONE shared password (no emp_id) stored in
# settings.md_password_hash — OR via OTP from the exact numbers listed in
# settings.md_otp_phones. Every attempt (success AND failure) is audited;
# password failures are rate-limited per-IP and globally.

MD_LOGIN_MAX_PER_IP = 5
MD_LOGIN_MAX_GLOBAL = 50
MD_LOGIN_WINDOW_SECONDS = 15 * 60


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _shared_md_account(session: AsyncSession) -> Employee | None:
    return (
        await session.execute(
            select(Employee).where(
                Employee.emp_id == "MD",
                Employee.is_active.is_(True),
                Employee.is_demo.is_(False),
            )
        )
    ).scalar_one_or_none()


@router.post("/auth/md-login")
async def md_login(
    body: MdLoginIn, request: Request, session: AsyncSession = Depends(get_session)
):
    """Shared-password MD login: the password ALONE opens the MD dashboard."""
    ip = _client_ip(request)
    ip_key = f"mdlogin:fail:ip:{ip}"
    global_key = "mdlogin:fail:global"
    ip_fails = int(await redis_client.get(ip_key) or 0)
    global_fails = int(await redis_client.get(global_key) or 0)
    if ip_fails >= MD_LOGIN_MAX_PER_IP or global_fails >= MD_LOGIN_MAX_GLOBAL:
        raise HTTPException(status_code=429, detail=PW_LOCKOUT_DETAIL)

    fs = (await session.execute(select(FactorySettings))).scalars().first()

    async def _fail():
        for key in (ip_key, global_key):
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, MD_LOGIN_WINDOW_SECONDS)
        await write_audit(
            session, None, "auth.md_login_failed", "settings", None, {"ip": ip}, is_demo=False
        )
        await session.commit()

    if (
        fs is None
        or not fs.md_password_hash
        or not verify_password(body.password, fs.md_password_hash)
    ):
        await _fail()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    md = await _shared_md_account(session)
    if md is None:
        await _fail()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await redis_client.delete(ip_key)
    await write_audit(session, md.id, "auth.md_login", "employee", str(md.id), {"ip": ip}, is_demo=False)
    await session.commit()
    tokens = create_token_pair(md)
    return {**tokens, "employee": employee_profile(md), "must_change_password": False}


@router.post("/auth/md-elevate")
async def md_elevate(
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    """OTP path to the MD dashboard: ONLY the numbers in settings.md_otp_phones
    (exactly two) may elevate to the shared MD account after a normal OTP login.
    Everyone else keeps their personal dashboard role (CGM / TO manager)."""
    fs = (await session.execute(select(FactorySettings))).scalars().first()
    whitelist = (
        {p.strip() for p in (fs.md_otp_phones or "").split(",") if p.strip()} if fs else set()
    )
    if not employee.phone or employee.phone not in whitelist:
        raise HTTPException(status_code=403, detail="This number is not authorized for MD access")
    md = await _shared_md_account(session)
    if md is None:
        raise HTTPException(status_code=503, detail="Shared MD account is not provisioned")
    await write_audit(
        session, md.id, "auth.md_elevate", "employee", str(md.id),
        {"phone": employee.phone, "via_employee": str(employee.id)}, is_demo=False,
    )
    await session.commit()
    tokens = create_token_pair(md)
    return {**tokens, "employee": employee_profile(md)}


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


@router.post("/employees/me/face-enroll")
async def face_enroll(
    body: FaceEnrollIn,
    employee: Employee = Depends(get_current_employee),
    session: AsyncSession = Depends(get_session),
):
    """Prompt 17 Part C: post-login face enrollment. Reuses the EXISTING
    reference-selfie bootstrap fields + supervised-review semantics — the newly
    set reference is announced to the Time Office manager, who can clear it via
    the existing reset-reference-selfie endpoint. Punch-time verification is
    untouched: it simply compares against this reference like any bootstrap."""
    if employee.reference_selfie_key:
        raise HTTPException(status_code=409, detail="Face reference already exists")
    employee.reference_selfie_key = body.selfie_key
    employee.reference_selfie_set_at = datetime.now(timezone.utc)
    await write_audit(
        session, employee.id, "employee.reference_selfie_from_enrollment",
        "employee", str(employee.id), {"selfie_key": body.selfie_key},
    )
    # supervised review: Time Office manager is informed (reset endpoint = reject path)
    from app.demo import resolve_dept_manager_id

    to_dept = (
        await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
    ).scalar_one_or_none()
    if to_dept:
        reviewer = await resolve_dept_manager_id(session, to_dept, employee.is_demo)
        if reviewer and reviewer != employee.id:
            title, notif_body = template(
                "face_enrolled", f"{employee.full_name} ({employee.emp_id})"
            )
            await dispatcher.notify(
                session, reviewer, "face_enrolled", title, notif_body,
                "employee", str(employee.id),
            )
    await session.commit()
    await session.refresh(employee)
    return employee_profile(employee)


@router.get("/app-version")
async def app_version(session: AsyncSession = Depends(get_session)):
    """Prompt 16: public version check for the mobile update-available banner."""
    row = (
        await session.execute(select(AppVersion).order_by(AppVersion.updated_at.desc()).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return {"latest_version": None, "apk_url": None, "notes": None, "force_update": False}
    return {
        "latest_version": row.latest_version,
        "apk_url": row.apk_url,
        "notes": row.notes,
        "force_update": row.force_update,
    }
