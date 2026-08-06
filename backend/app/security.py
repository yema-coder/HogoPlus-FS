import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Department, Employee

bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"

# ---- Password auth (webdash MD/CGM only) — passlib bcrypt ----
from passlib.context import CryptContext  # noqa: E402

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_token_pair(employee: Employee) -> dict:
    now = datetime.now(timezone.utc)
    base = {"sub": str(employee.id), "emp_id": employee.emp_id, "role": employee.role_code}
    access = jwt.encode(
        {**base, "type": "access", "iat": now, "exp": now + timedelta(hours=settings.access_token_hours)},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    refresh = jwt.encode(
        {**base, "type": "refresh", "jti": str(uuid.uuid4()), "iat": now,
         "exp": now + timedelta(days=settings.refresh_token_days)},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    return payload


def create_registration_token(phone: str) -> str:
    """Short-lived token proving OTP verification of an unknown phone (self-registration)."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "phone": phone,
            "type": "registration",
            "scope": "registration",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


async def get_access_or_registration_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Accepts a full access token OR a 15-min registration token. 401 otherwise."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") not in ("access", "registration"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    return payload


async def get_current_employee(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Employee:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials, "access")
    try:
        emp_uuid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    employee = await session.get(Employee, emp_uuid)
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Employee not found or inactive")
    return employee


async def get_approved_employee(
    employee: Employee = Depends(get_current_employee),
) -> Employee:
    if employee.onboarding_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval. Access restricted to incident reporting and profile.",
        )
    return employee


def require_role(min_rank: int):
    """Dependency factory: allow only employees whose role rank <= min_rank (1=MD highest)."""

    async def _dep(employee: Employee = Depends(get_approved_employee)) -> Employee:
        if employee.role.rank > min_rank:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return employee

    return _dep


def require_real_role(min_rank: int):
    """Like require_role but ALSO blocks demo showcase accounts — used on endpoints
    that mutate SHARED factory configuration (settings, beacons, forms, SOPs, SMS,
    reports). Demo users may read shared config but never change it."""

    async def _dep(employee: Employee = Depends(require_role(min_rank))) -> Employee:
        if employee.is_demo:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo accounts cannot modify shared factory configuration",
            )
        return employee

    return _dep


async def is_dept_manager(session: AsyncSession, employee: Employee, department_code: str) -> bool:
    """True if the employee manages the department: CGM/MD always, explicit dept manager,
    or role Manager belonging to that department."""
    if employee.role.rank <= 2:
        return True
    dept = (
        await session.execute(select(Department).where(Department.code == department_code))
    ).scalar_one_or_none()
    if dept is not None and dept.manager_employee_id == employee.id:
        return True
    if employee.role_code == "Manager" and employee.department_code == department_code:
        return True
    return False


def employee_profile(employee: Employee) -> dict:
    dept = employee.department
    role = employee.role
    return {
        "id": str(employee.id),
        "emp_id": employee.emp_id,
        "full_name": employee.full_name,
        "phone": employee.phone,
        "department_code": employee.department_code,
        "department": {
            "code": dept.code, "name_en": dept.name_en,
            "name_hi": dept.name_hi, "name_mr": dept.name_mr,
        } if dept else None,
        # v1.0.24: drives the mobile "Add employee" entry — CGM/MD always; a
        # Manager (or explicit HOD) of a can_add_employees department (HEAD_OFFICE).
        "can_add_employees": bool(
            (role and role.rank <= 2)
            or (
                dept
                and dept.can_add_employees
                and (employee.role_code == "Manager" or dept.manager_employee_id == employee.id)
            )
        ),
        "designation": employee.designation,
        "role_code": employee.role_code,
        "role": {
            "code": role.code, "rank": role.rank, "label_en": role.label_en,
            "label_hi": role.label_hi, "label_mr": role.label_mr,
        } if role else None,
        "language_pref": employee.language_pref,
        "shift_swap_eligible": employee.shift_swap_eligible,
        "onboarding_status": employee.onboarding_status,
        "selfie_url": employee.selfie_url,
        "is_active": employee.is_active,
        "has_face_reference": bool(employee.reference_selfie_key),
    }
