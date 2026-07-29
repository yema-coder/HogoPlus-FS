import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
    AppVersion,
    AuditEvent,
    BleBeacon,
    Department,
    Employee,
    FactorySettings,
    FormDefinition,
    Role,
    Shift,
    ShiftAssignment,
)
from app.notify import dispatcher, template
from app.schemas import (
    AnnouncementIn,
    AppVersionIn,
    AssignManagerIn,
    DirectAddEmployeeIn,
    ApproveRegistrationIn,
    BeaconIn,
    BeaconBulkIn,
    BeaconPatchIn,
    EmployeePatchIn,
    FormDefCreateIn,
    FormDefPatchIn,
    GenerateReportIn,
    PurgeDemoIn,
    RejectIn,
    SetPasswordIn,
    SettingsPatchIn,
    TestSmsIn,
)
from app.security import (
    employee_profile,
    get_approved_employee,
    hash_password,
    is_dept_manager,
    require_real_role,
    require_role,
)
from app.shift_logic import now_ist

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_time_office_or_top(session: AsyncSession, employee: Employee):
    if not await is_dept_manager(session, employee, "TIME_OFFICE"):
        raise HTTPException(status_code=403, detail="Time Office Manager / CGM / MD only")


# ---------------- settings ----------------

@router.get("/settings")
async def get_settings(
    employee: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Settings not seeded")
    return {
        "factory_lat": s.factory_lat, "factory_lng": s.factory_lng,
        "radius_meters": s.radius_meters, "beacon_first_mode": s.beacon_first_mode,
    }


@router.patch("/settings")
async def patch_settings(
    body: SettingsPatchIn,
    employee: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Settings not seeded")
    changes = {}
    for field in ("factory_lat", "factory_lng", "radius_meters", "beacon_first_mode"):
        val = getattr(body, field)
        if val is not None:
            changes[field] = {"old": getattr(s, field), "new": val}
            setattr(s, field, val)
    await write_audit(session, employee.id, "settings.updated", "settings", str(s.id), changes)
    await session.commit()
    return {
        "factory_lat": s.factory_lat, "factory_lng": s.factory_lng,
        "radius_meters": s.radius_meters, "beacon_first_mode": s.beacon_first_mode,
    }


# ---------------- employees ----------------

@router.patch("/employees/{employee_id}")
async def patch_employee(
    employee_id: uuid.UUID,
    body: EmployeePatchIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_time_office_or_top(session, actor)
    emp = await session.get(Employee, employee_id)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Prompt 17 guardrails, Prompt 21 update: Time Office manages Worker/Staff/Clerk
    # AND Manager accounts (to install/replace HODs without the CGM in the loop) and
    # may grant the Manager role. CGM/MD accounts and roles remain CGM/MD-only —
    # in both directions. Every change is written to the audit log below.
    if actor.role.rank > 2:
        target_role = (
            await session.execute(select(Role).where(Role.code == emp.role_code))
        ).scalar_one()
        if target_role.rank <= 2:
            raise HTTPException(status_code=403, detail="Only CGM/MD can modify CGM/MD accounts")
        if body.role_code is not None:
            new_role = (
                await session.execute(select(Role).where(Role.code == body.role_code))
            ).scalar_one_or_none()
            if new_role and new_role.rank <= 2:
                raise HTTPException(status_code=403, detail="Only CGM/MD can grant CGM/MD roles")

    changes = {}
    if body.phone is not None:
        dup = (
            await session.execute(
                select(Employee).where(Employee.phone == body.phone, Employee.id != emp.id)
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="Phone already in use")
        changes["phone"] = {"old": emp.phone, "new": body.phone}
        emp.phone = body.phone
        if emp.onboarding_status == "seeded":
            emp.onboarding_status = "approved"
            changes["onboarding_status"] = {"old": "seeded", "new": "approved"}
    if body.full_name is not None:
        changes["full_name"] = {"old": emp.full_name, "new": body.full_name}
        emp.full_name = body.full_name
    if body.role_code is not None:
        role = (await session.execute(select(Role).where(Role.code == body.role_code))).scalar_one_or_none()
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        changes["role_code"] = {"old": emp.role_code, "new": body.role_code}
        emp.role_code = body.role_code
    if body.department_code is not None:
        dept = (
            await session.execute(select(Department).where(Department.code == body.department_code))
        ).scalar_one_or_none()
        if dept is None:
            raise HTTPException(status_code=404, detail="Department not found")
        changes["department_code"] = {"old": emp.department_code, "new": body.department_code}
        emp.department_code = body.department_code
    if body.shift_code is not None:
        shift = (await session.execute(select(Shift).where(Shift.code == body.shift_code))).scalar_one_or_none()
        if shift is None:
            raise HTTPException(status_code=404, detail="Shift not found")
        today = now_ist().date()
        existing = (
            await session.execute(
                select(ShiftAssignment).where(
                    ShiftAssignment.employee_id == emp.id,
                    ShiftAssignment.effective_date == today,
                    ShiftAssignment.source == "baseline",
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.shift_code = body.shift_code
        else:
            session.add(
                ShiftAssignment(
                    employee_id=emp.id, shift_code=body.shift_code,
                    effective_date=today, source="baseline",
                )
            )
        changes["shift_code"] = {"new": body.shift_code}
    if body.is_active is not None:
        changes["is_active"] = {"old": emp.is_active, "new": body.is_active}
        emp.is_active = body.is_active

    await write_audit(session, actor.id, "employee.updated", "employee", str(emp.id), changes)
    await session.commit()
    await session.refresh(emp)
    return employee_profile(emp)


@router.post("/employees/{employee_id}/approve")
async def approve_employee(
    employee_id: uuid.UUID,
    body: ApproveRegistrationIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    emp = await session.get(Employee, employee_id)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")
    # Time Office assigns everything: TIME_OFFICE manager or CGM/MD only
    allowed = actor.role.rank <= 2 or await is_dept_manager(session, actor, "TIME_OFFICE")
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to approve registrations")
    if emp.onboarding_status not in ("pending_approval", "self_registered"):
        raise HTTPException(status_code=409, detail=f"Employee is {emp.onboarding_status}")
    dept = (
        await session.execute(select(Department).where(Department.code == body.department_code))
    ).scalar_one_or_none()
    if dept is None or not dept.is_active:
        raise HTTPException(status_code=404, detail="Department not found")
    if body.role_code not in ("Worker", "Staff", "Clerk", "Manager"):
        raise HTTPException(status_code=422, detail="Invalid role for registration approval")
    dup = (
        await session.execute(
            select(Employee).where(Employee.emp_id == body.emp_id, Employee.id != emp.id)
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail=f"emp_id {body.emp_id} is already taken")
    emp.department_code = body.department_code
    emp.role_code = body.role_code
    emp.emp_id = body.emp_id
    emp.onboarding_status = "approved"
    # self-registered workers: the approved registration selfie becomes the face reference
    if emp.selfie_url and not emp.reference_selfie_key:
        emp.reference_selfie_key = emp.selfie_url.rsplit("/", 1)[-1]
        emp.reference_selfie_set_at = now_ist()
        await write_audit(
            session, actor.id, "employee.reference_selfie_from_registration",
            "employee", str(emp.id), {"selfie_key": emp.reference_selfie_key},
        )
    await write_audit(
        session, actor.id, "employee.approved", "employee", str(emp.id),
        {"department_code": body.department_code, "role_code": body.role_code, "emp_id": body.emp_id},
    )
    title, body = template("registration_approved", emp.full_name)
    await dispatcher.notify(session, emp.id, "registration_approved", title, body, "employee", str(emp.id))
    await session.commit()
    await session.refresh(emp)
    return employee_profile(emp)


@router.post("/employees/{employee_id}/set-password")
async def set_employee_password(
    employee_id: uuid.UUID,
    body: SetPasswordIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """CGM/MD only: set a TEMPORARY dashboard password (must be changed on first login)."""
    if actor.role.rank > 2:
        raise HTTPException(status_code=403, detail="Only CGM/MD can set passwords")
    emp = await session.get(Employee, employee_id)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.password_hash = hash_password(body.password)
    emp.must_change_password = True
    await write_audit(
        session, actor.id, "employee.password_set", "employee", str(emp.id),
        {"set_by": actor.emp_id},
    )
    await session.commit()
    return {"status": "temporary_password_set", "emp_id": emp.emp_id, "must_change_password": True}


@router.post("/employees/{employee_id}/reject")
async def reject_employee(
    employee_id: uuid.UUID,
    body: RejectIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    emp = await session.get(Employee, employee_id)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")
    allowed = await is_dept_manager(session, actor, "TIME_OFFICE") or await is_dept_manager(
        session, actor, emp.department_code
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    if emp.onboarding_status not in ("pending_approval", "self_registered"):
        raise HTTPException(status_code=409, detail=f"Employee is {emp.onboarding_status}")
    emp.onboarding_status = "rejected"
    await write_audit(session, actor.id, "employee.rejected", "employee", str(emp.id), {"reason": body.reason})
    await session.commit()
    return employee_profile(emp)


@router.get("/employees/pending")
async def pending_employees(
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    allowed = await is_dept_manager(session, actor, "TIME_OFFICE") or actor.role.rank <= 3
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    query = select(Employee).where(
        Employee.onboarding_status == "pending_approval",
        Employee.is_demo == actor.is_demo,
    )
    if actor.role.rank == 3 and not await is_dept_manager(session, actor, "TIME_OFFICE"):
        query = query.where(Employee.department_code == actor.department_code)
    rows = (await session.execute(query.order_by(Employee.created_at.desc()))).scalars().all()
    # suggest the next free numeric emp_id for the Time Office approval form
    from sqlalchemy import Integer as SAInteger, cast, func

    max_num = (
        await session.execute(
            select(func.max(cast(Employee.emp_id, SAInteger))).where(Employee.emp_id.op("~")(r"^\d+$"))
        )
    ).scalar() or 0
    suggested = f"{max_num + 1:04d}"
    return [{**employee_profile(e), "suggested_emp_id": suggested} for e in rows]


@router.get("/employees")
async def search_employees(
    search: str | None = None,
    missing_phone: bool = False,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Employee lookup for the admin screens (Time Office Manager / CGM / MD)."""
    await _require_time_office_or_top(session, actor)
    query = select(Employee).where(
        Employee.is_active.is_(True), Employee.is_demo == actor.is_demo
    )
    if missing_phone:
        query = query.where(Employee.phone.is_(None))
    if search:
        like = f"%{search}%"
        query = query.where(
            Employee.full_name.ilike(like)
            | Employee.emp_id.ilike(like)
            | Employee.phone.ilike(like)
        )
    rows = (await session.execute(query.order_by(Employee.emp_id).limit(25))).scalars().all()
    return [employee_profile(e) for e in rows]


# ---------------- departments ----------------

@router.post("/departments/{code}/assign-manager")
async def assign_manager(
    code: str,
    body: AssignManagerIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    # Prompt 21: Time Office managers may (re)assign department HODs. Rails: demo
    # actors never touch the shared departments table; Time Office may only install
    # employees who already hold the Manager role; audited below.
    await _require_time_office_or_top(session, actor)
    if actor.is_demo:
        raise HTTPException(
            status_code=403, detail="Demo accounts cannot modify shared factory configuration"
        )
    dept = (await session.execute(select(Department).where(Department.code == code))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    emp = await session.get(Employee, body.employee_id)
    if emp is None or not emp.is_active or emp.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")
    if actor.role.rank > 2:
        emp_role = (
            await session.execute(select(Role).where(Role.code == emp.role_code))
        ).scalar_one()
        if emp_role.rank != 3:
            raise HTTPException(status_code=403, detail="HOD must hold the Manager role")
    old = dept.manager_employee_id
    dept.manager_employee_id = emp.id
    await write_audit(
        session, actor.id, "department.assign_manager", "department", code,
        {"old": str(old) if old else None, "new": str(emp.id)},
    )
    await session.commit()
    return {"department_code": code, "manager_employee_id": str(emp.id), "manager_name": emp.full_name}


# ---------------- beacons ----------------

def _beacon_out(b: BleBeacon) -> dict:
    mode = "mac" if b.mac_address else ("ibeacon" if b.beacon_uuid else "unknown")
    return {
        "id": str(b.id),
        "mode": mode,
        "beacon_uuid": b.beacon_uuid,
        "mac_address": b.mac_address,
        "major": b.major,
        "minor": b.minor,
        "zone_label_en": b.zone_label_en,
        "zone_label_hi": b.zone_label_hi,
        "zone_label_mr": b.zone_label_mr,
        "department_code": b.department_code,
        "is_active": b.is_active,
    }


@router.get("/beacons")
async def list_beacons(
    actor: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(BleBeacon).order_by(BleBeacon.created_at))).scalars().all()
    return [_beacon_out(b) for b in rows]


@router.post("/beacons")
async def create_beacon(
    body: BeaconIn,
    actor: Employee = Depends(require_real_role(3)),
    session: AsyncSession = Depends(get_session),
):
    beacon = BleBeacon(**body.model_dump())
    session.add(beacon)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Beacon already registered (MAC or UUID/Major/Minor)")
    await write_audit(
        session, actor.id, "beacon.created", "ble_beacon", str(beacon.id),
        {"uuid": body.beacon_uuid, "mac": body.mac_address, "major": body.major, "minor": body.minor},
    )
    await session.commit()
    await session.refresh(beacon)
    return _beacon_out(beacon)


@router.post("/beacons/bulk")
async def bulk_import_beacons(
    body: BeaconBulkIn,
    actor: Employee = Depends(require_real_role(3)),
    session: AsyncSession = Depends(get_session),
):
    """Register many iBeacon units at once from one shared UUID + Major and a list of
    (minor, zone_name) rows. Skips minors already registered to this UUID/Major.
    Reports how many were added vs skipped."""
    if body.department_code:
        dept = (
            await session.execute(select(Department).where(Department.code == body.department_code))
        ).scalar_one_or_none()
        if dept is None:
            raise HTTPException(status_code=404, detail="Department not found")

    existing = (
        await session.execute(
            select(BleBeacon.minor).where(
                BleBeacon.beacon_uuid == body.beacon_uuid,
                BleBeacon.major == body.major,
            )
        )
    ).scalars().all()
    existing_minors = set(existing)

    added, skipped = 0, 0
    seen: set[int] = set()
    for row in body.rows:
        if row.minor in existing_minors or row.minor in seen:
            skipped += 1
            continue
        seen.add(row.minor)
        session.add(
            BleBeacon(
                beacon_uuid=body.beacon_uuid, major=body.major, minor=row.minor,
                mac_address=None,
                zone_label_en=row.zone_name, zone_label_hi=row.zone_name, zone_label_mr=row.zone_name,
                department_code=body.department_code, is_active=True,
            )
        )
        added += 1
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate (UUID, Major, Minor) in import")
    await write_audit(
        session, actor.id, "beacon.bulk_import", "ble_beacon", None,
        {"uuid": body.beacon_uuid, "major": body.major, "added": added, "skipped": skipped},
    )
    await session.commit()
    return {"added": added, "skipped": skipped, "total": len(body.rows)}


@router.patch("/beacons/{beacon_id}")
async def patch_beacon(
    beacon_id: uuid.UUID,
    body: BeaconPatchIn,
    actor: Employee = Depends(require_real_role(3)),
    session: AsyncSession = Depends(get_session),
):
    beacon = await session.get(BleBeacon, beacon_id)
    if beacon is None:
        raise HTTPException(status_code=404, detail="Beacon not found")
    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        setattr(beacon, k, v)
    await write_audit(session, actor.id, "beacon.updated", "ble_beacon", str(beacon.id), updates)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Beacon already registered (MAC or UUID/Major/Minor)")
    await session.refresh(beacon)
    return _beacon_out(beacon)


@router.delete("/beacons/{beacon_id}")
async def delete_beacon(
    beacon_id: uuid.UUID,
    actor: Employee = Depends(require_real_role(3)),
    session: AsyncSession = Depends(get_session),
):
    beacon = await session.get(BleBeacon, beacon_id)
    if beacon is None:
        raise HTTPException(status_code=404, detail="Beacon not found")
    await session.delete(beacon)
    await write_audit(session, actor.id, "beacon.deleted", "ble_beacon", str(beacon_id), {})
    await session.commit()
    return {"deleted": True}


# ---------------- form definitions ----------------

@router.post("/forms")
async def create_form(
    body: FormDefCreateIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    if actor.is_demo:
        raise HTTPException(status_code=403, detail="Demo accounts cannot modify shared factory configuration")
    if not await is_dept_manager(session, actor, body.department_code):
        raise HTTPException(status_code=403, detail="Only the department Manager or above")
    dept = (
        await session.execute(select(Department).where(Department.code == body.department_code))
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if not isinstance(body.schema_json.get("fields"), list) or not body.schema_json["fields"]:
        raise HTTPException(status_code=400, detail="schema_json.fields must be a non-empty list")
    existing = (
        await session.execute(
            select(FormDefinition).where(
                FormDefinition.department_code == body.department_code, FormDefinition.code == body.code
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Form code already exists for this department")
    form = FormDefinition(**body.model_dump())
    session.add(form)
    await session.flush()
    await write_audit(session, actor.id, "form_definition.created", "form_definition", str(form.id), {"code": body.code})
    await session.commit()
    await session.refresh(form)
    from app.routers.forms import _def_out

    return _def_out(form)


@router.patch("/forms/{form_id}")
async def patch_form(
    form_id: uuid.UUID,
    body: FormDefPatchIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    form = await session.get(FormDefinition, form_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    if actor.is_demo:
        raise HTTPException(status_code=403, detail="Demo accounts cannot modify shared factory configuration")
    if not await is_dept_manager(session, actor, form.department_code):
        raise HTTPException(status_code=403, detail="Only the department Manager or above")
    updates = body.model_dump(exclude_none=True)
    if "schema_json" in updates:
        if not isinstance(updates["schema_json"].get("fields"), list) or not updates["schema_json"]["fields"]:
            raise HTTPException(status_code=400, detail="schema_json.fields must be a non-empty list")
        form.version += 1  # old submissions keep their form_version reference
    for k, v in updates.items():
        setattr(form, k, v)
    await write_audit(session, actor.id, "form_definition.updated", "form_definition", str(form.id), {"fields": list(updates.keys()), "version": form.version})
    await session.commit()
    await session.refresh(form)
    from app.routers.forms import _def_out

    return _def_out(form)


# ---------------- Phase 4: face reference, backups, SOP docs, AI usage, reports ----------------


@router.post("/employees/{employee_id}/reset-reference-selfie")
async def reset_reference_selfie(
    employee_id: uuid.UUID,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Clears the face reference; the employee's NEXT punch-in selfie re-bootstraps it."""
    await _require_time_office_or_top(session, actor)
    emp = await session.get(Employee, employee_id)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Employee not found")
    old_key = emp.reference_selfie_key
    emp.reference_selfie_key = None
    emp.reference_selfie_set_at = None
    await write_audit(
        session, actor.id, "employee.reference_selfie_reset", "employee",
        str(emp.id), {"previous_key": old_key},
    )
    await session.commit()
    return {"id": str(emp.id), "reference_selfie_key": None, "message": "Next punch-in selfie will become the new reference"}


@router.post("/backup-now")
async def backup_now(
    actor: Employee = Depends(require_real_role(2)),
):
    """Manual DB backup trigger (CGM/MD only) — pg_dump → gzip → R2, keep last 14."""
    from starlette.concurrency import run_in_threadpool

    from app.tasks import run_backup_sync

    try:
        result = await run_in_threadpool(run_backup_sync)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Backup failed: {type(e).__name__}")
    return result


@router.post("/test-sms")
async def test_sms(
    body: TestSmsIn,
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """Send a REAL OTP SMS via SMSGatewayHub (regardless of OTP_MODE) and return the
    provider's raw response JSON so delivery can be verified before switching modes.
    CGM/MD only."""
    import secrets

    from app.otp import NotConfigured, SMSDeliveryError, SMSGatewayHubSender
    from app.redis_client import redis_client
    from app.routers.auth import OTP_TTL_SECONDS, _hash

    try:
        sender = SMSGatewayHubSender()
    except NotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    otp = f"{secrets.randbelow(10**6):06d}"
    # store like the real login flow so the delivered OTP is actually usable
    await redis_client.setex(f"otp:code:{body.phone}", OTP_TTL_SECONDS, _hash(otp))
    await write_audit(session, actor.id, "admin.test_sms", "employee", str(actor.id), {"phone": body.phone})
    await session.commit()
    try:
        raw = await sender.send_raw(body.phone, otp)
    except SMSDeliveryError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider call failed: {type(e).__name__}: {e}")
    return {"sent": True, "otp_mode": "smsgatewayhub", "provider_response": raw}


MAX_SOP_SIZE = 20 * 1024 * 1024


@router.post("/sop-docs")
async def upload_sop_doc(
    file: UploadFile,
    background: BackgroundTasks,
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """SOP PDF upload (CGM/MD only) → R2 → in-process: extract, chunk, embed into pgvector."""
    from app.models import SopDoc
    from app.storage import get_storage

    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if len(content) > MAX_SOP_SIZE:
        raise HTTPException(status_code=413, detail="PDF exceeds 20 MB limit")
    key = await get_storage().save(content, "pdf")
    doc = SopDoc(
        title=(file.filename or "SOP document").rsplit(".", 1)[0][:300],
        file_key=key,
        status="pending",
        uploaded_by=actor.id,
    )
    session.add(doc)
    await write_audit(session, actor.id, "sop_doc.uploaded", "sop_doc", str(doc.id), {"title": doc.title})
    await session.commit()
    await session.refresh(doc)
    # SOP ingest runs AFTER the response, IN-PROCESS (production has no Celery worker)
    if not os.environ.get("TESTING"):
        from app.tasks import run_sop_ingest_background

        background.add_task(run_sop_ingest_background, str(doc.id))
    return _sop_doc_out(doc)


def _sop_doc_out(d) -> dict:
    return {
        "id": str(d.id),
        "title": d.title,
        "file_key": d.file_key,
        "page_count": d.page_count,
        "chunk_count": d.chunk_count,
        "status": d.status,
        "error": d.error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/sop-docs")
async def list_sop_docs(
    actor: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    from app.models import SopDoc

    docs = (
        (await session.execute(select(SopDoc).order_by(SopDoc.created_at.desc()))).scalars().all()
    )
    return [_sop_doc_out(d) for d in docs]


@router.delete("/sop-docs/{doc_id}")
async def delete_sop_doc(
    doc_id: uuid.UUID,
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    from starlette.concurrency import run_in_threadpool

    from app.models import SopDoc
    from app.storage import get_storage

    doc = await session.get(SopDoc, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        await run_in_threadpool(get_storage().delete, doc.file_key)
    except Exception:
        pass  # storage object removal is best-effort
    await write_audit(session, actor.id, "sop_doc.deleted", "sop_doc", str(doc.id), {"title": doc.title})
    await session.delete(doc)  # sop_chunks cascade via FK ondelete
    await session.commit()
    return {"deleted": str(doc_id)}


@router.get("/ai-usage")
async def ai_usage(
    date: str | None = None,
    actor: Employee = Depends(require_role(2)),
):
    """Daily AI call counters by type + 7-day history (CGM/MD only)."""
    from datetime import timedelta

    from app import ai_core

    target = date or now_ist().date().isoformat()
    result = await ai_core.usage_for_date(target, actor.is_demo)
    today = now_ist().date()
    history = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        day = await ai_core.usage_for_date(d, actor.is_demo)
        history.append({"date": d, "total": sum(day["counts"].values()), "counts": day["counts"]})
    result["history"] = history
    return result


@router.post("/generate-report")
async def generate_report(
    body: GenerateReportIn,
    actor: Employee = Depends(require_real_role(2)),
):
    """Manual factory-report trigger for demos (CGM/MD only)."""
    from datetime import timedelta

    from app.tasks import generate_report_async

    target = body.date or (now_ist().date() - timedelta(days=1))
    try:
        return await generate_report_async(target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Report generation failed: {type(e).__name__}")


# ---------------- Prompt 14: demo bubble purge ----------------

@router.post("/purge-demo-data")
async def purge_demo_data(
    body: PurgeDemoIn,
    actor: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """REAL CGM/MD only: purge judge-created demo data of ANY age (and their R2
    media). dry_run=true reports what would be deleted without touching anything.
    include_seed=true additionally wipes the permanent showcase seed data."""
    if actor.is_demo:
        raise HTTPException(status_code=403, detail="Real CGM/MD only")
    from app.demo_cleanup import run_demo_cleanup

    result = await run_demo_cleanup(
        session,
        dry_run=body.dry_run,
        include_seed=body.include_seed,
        older_than_minutes=None,
    )
    if not body.dry_run:
        await write_audit(
            session, actor.id, "admin.purge_demo_data", "demo_data", None,
            {**result, "include_seed": body.include_seed}, is_demo=False,
        )
        await session.commit()
    return result


@router.put("/app-version")
async def set_app_version(
    body: AppVersionIn,
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """Prompt 16: update the single app-version row that drives the mobile update banner."""
    row = (
        await session.execute(select(AppVersion).order_by(AppVersion.updated_at.desc()).limit(1))
    ).scalar_one_or_none()
    if row is None:
        row = AppVersion(latest_version=body.latest_version)
        session.add(row)
    row.latest_version = body.latest_version
    row.apk_url = body.apk_url
    row.notes = body.notes
    row.force_update = body.force_update
    await write_audit(session, actor.id, "admin.app_version", "app_version", None,
                      {"latest_version": body.latest_version, "force_update": body.force_update},
                      is_demo=False)
    await session.commit()
    return {
        "latest_version": row.latest_version,
        "apk_url": row.apk_url,
        "notes": row.notes,
        "force_update": row.force_update,
    }


# ---------------- Prompt 17: direct-add employee + emp-id suggest ----------------

@router.get("/emp-id-suggest")
async def emp_id_suggest(
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_time_office_or_top(session, actor)
    from sqlalchemy import text as sa_text

    row = (
        await session.execute(
            sa_text(r"SELECT COALESCE(MAX(emp_id::int), 0) FROM employees WHERE emp_id ~ '^\d+$'")
        )
    ).scalar() or 0
    return {"suggested_emp_id": f"{row + 1:04d}"}


@router.post("/employees")
async def direct_add_employee(
    body: DirectAddEmployeeIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Time Office Manager: Worker/Staff/Clerk/Manager. CGM/MD: any role.
    Created ACTIVE immediately — first login lands on the role's home."""
    await _require_time_office_or_top(session, actor)
    role = (await session.execute(select(Role).where(Role.code == body.role_code))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    # Prompt 21: Time Office may also create Manager accounts (onboarding new HODs);
    # CGM/MD accounts remain CGM/MD-only.
    if actor.role.rank > 2 and role.rank <= 2:
        raise HTTPException(status_code=403, detail="Only CGM/MD can create CGM/MD accounts")
    dept = (
        await session.execute(select(Department).where(Department.code == body.department_code))
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    for field, val in (("phone", body.phone), ("emp_id", body.emp_id)):
        dup = (
            await session.execute(select(Employee).where(getattr(Employee, field) == val))
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"{field} already in use")

    emp = Employee(
        emp_id=body.emp_id, full_name=body.full_name, phone=body.phone,
        department_code=body.department_code, role_code=body.role_code,
        designation=role.label_en, language_pref="mr",
        shift_swap_eligible=role.rank >= 4, onboarding_status="approved",
        is_active=True, is_demo=actor.is_demo,
    )
    session.add(emp)
    await session.flush()
    session.add(ShiftAssignment(
        employee_id=emp.id, shift_code=body.shift_code or "GEN",
        effective_date=now_ist().date(), source="baseline",
    ))
    await write_audit(
        session, actor.id, "employee.direct_added", "employee", str(emp.id),
        {"emp_id": body.emp_id, "role": body.role_code, "dept": body.department_code},
    )
    title, note = template("welcome", "")
    note = {
        "en": f"Your HogoPlus account is ready, {body.full_name.split()[0]}. Punch in and explore!",
        "hi": f"आपका HogoPlus खाता तैयार है, {body.full_name.split()[0]}। हाज़िरी लगाएँ और शुरू करें!",
        "mr": f"तुमचे HogoPlus खाते तयार आहे, {body.full_name.split()[0]}. हजेरी लावा आणि सुरुवात करा!",
    }
    await dispatcher.notify(session, emp.id, "welcome", title, note, "employee", str(emp.id))
    await session.commit()
    await session.refresh(emp)
    return employee_profile(emp)


# ---------------- Prompt 17 Part F: announcements ----------------

@router.post("/announcements")
async def send_announcement(
    body: AnnouncementIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Managers announce to their OWN department; CGM/MD to any department or all.
    Fanout = in-app notification (+ push mirror) per recipient in scope."""
    rank = actor.role.rank
    if rank > 3:
        raise HTTPException(status_code=403, detail="Manager / CGM / MD only")
    if body.audience == "all":
        if rank > 2:
            raise HTTPException(status_code=403, detail="Only CGM/MD can announce to everyone")
    else:
        if not body.department_code:
            raise HTTPException(status_code=422, detail="department_code required")
        if rank > 2 and not await is_dept_manager(session, actor, body.department_code):
            raise HTTPException(status_code=403, detail="Managers can announce to their own department only")
        dept = (
            await session.execute(select(Department).where(Department.code == body.department_code))
        ).scalar_one_or_none()
        if dept is None:
            raise HTTPException(status_code=404, detail="Department not found")

    query = select(Employee.id).where(
        Employee.is_active.is_(True),
        Employee.onboarding_status == "approved",
        Employee.is_demo.is_(actor.is_demo),
        Employee.id != actor.id,
        Employee.phone.isnot(None),
    )
    if body.audience == "department":
        query = query.where(Employee.department_code == body.department_code)
    recipient_ids = (await session.execute(query)).scalars().all()

    title = {"en": f"📢 {body.title}", "hi": f"📢 {body.title}", "mr": f"📢 {body.title}"}
    message = {"en": body.message, "hi": body.message, "mr": body.message}
    for rid in recipient_ids:
        await dispatcher.notify(session, rid, "announcement", title, message, "announcement", None)
    await write_audit(
        session, actor.id, "announcement.sent", "announcement", None,
        {"audience": body.audience, "department_code": body.department_code,
         "title": body.title, "recipients": len(recipient_ids)},
    )
    await session.commit()
    return {"sent": True, "recipients": len(recipient_ids), "audience": body.audience}


@router.get("/ble-diag")
async def list_ble_diag(
    limit: int = 10,
    actor: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """v1.0.16 field instrumentation: read the most recent on-device BLE diagnostic
    reports submitted via POST /api/attendance/ble-diag."""
    limit = max(1, min(limit, 50))
    rows = (
        await session.execute(
            select(AuditEvent, Employee.emp_id, Employee.full_name)
            .join(Employee, Employee.id == AuditEvent.actor_id, isouter=True)
            .where(AuditEvent.action == "ble.diag")
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(ev.id),
            "emp_id": emp_id,
            "name": full_name,
            "created_at": ev.created_at,
            "report": ev.detail_json,
        }
        for ev, emp_id, full_name in rows
    ]
