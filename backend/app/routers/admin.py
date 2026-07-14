import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
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
    AssignManagerIn,
    BeaconIn,
    BeaconPatchIn,
    EmployeePatchIn,
    FormDefCreateIn,
    FormDefPatchIn,
    RejectIn,
    SettingsPatchIn,
)
from app.security import employee_profile, get_approved_employee, is_dept_manager, require_role
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
    return {"factory_lat": s.factory_lat, "factory_lng": s.factory_lng, "radius_meters": s.radius_meters}


@router.patch("/settings")
async def patch_settings(
    body: SettingsPatchIn,
    employee: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Settings not seeded")
    changes = {}
    for field in ("factory_lat", "factory_lng", "radius_meters"):
        val = getattr(body, field)
        if val is not None:
            changes[field] = {"old": getattr(s, field), "new": val}
            setattr(s, field, val)
    await write_audit(session, employee.id, "settings.updated", "settings", str(s.id), changes)
    await session.commit()
    return {"factory_lat": s.factory_lat, "factory_lng": s.factory_lng, "radius_meters": s.radius_meters}


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
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

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
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    emp = await session.get(Employee, employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    # Time Office manager, the Manager of the employee's chosen department, or CGM/MD
    allowed = await is_dept_manager(session, actor, "TIME_OFFICE") or await is_dept_manager(
        session, actor, emp.department_code
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to approve registrations")
    if emp.onboarding_status not in ("pending_approval", "self_registered"):
        raise HTTPException(status_code=409, detail=f"Employee is {emp.onboarding_status}")
    emp.onboarding_status = "approved"
    await write_audit(session, actor.id, "employee.approved", "employee", str(emp.id), {})
    title, body = template("registration_approved", emp.full_name)
    await dispatcher.notify(session, emp.id, "registration_approved", title, body, "employee", str(emp.id))
    await session.commit()
    await session.refresh(emp)
    return employee_profile(emp)


@router.post("/employees/{employee_id}/reject")
async def reject_employee(
    employee_id: uuid.UUID,
    body: RejectIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    emp = await session.get(Employee, employee_id)
    if emp is None:
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
    query = select(Employee).where(Employee.onboarding_status == "pending_approval")
    if actor.role.rank == 3 and not await is_dept_manager(session, actor, "TIME_OFFICE"):
        query = query.where(Employee.department_code == actor.department_code)
    rows = (await session.execute(query.order_by(Employee.created_at.desc()))).scalars().all()
    return [employee_profile(e) for e in rows]


# ---------------- departments ----------------

@router.post("/departments/{code}/assign-manager")
async def assign_manager(
    code: str,
    body: AssignManagerIn,
    actor: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    dept = (await session.execute(select(Department).where(Department.code == code))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    emp = await session.get(Employee, body.employee_id)
    if emp is None or not emp.is_active:
        raise HTTPException(status_code=404, detail="Employee not found")
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
    return {
        "id": str(b.id),
        "beacon_uuid": b.beacon_uuid,
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
    actor: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    beacon = BleBeacon(**body.model_dump())
    session.add(beacon)
    await session.flush()
    await write_audit(session, actor.id, "beacon.created", "ble_beacon", str(beacon.id), {"uuid": body.beacon_uuid})
    await session.commit()
    await session.refresh(beacon)
    return _beacon_out(beacon)


@router.patch("/beacons/{beacon_id}")
async def patch_beacon(
    beacon_id: uuid.UUID,
    body: BeaconPatchIn,
    actor: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    beacon = await session.get(BleBeacon, beacon_id)
    if beacon is None:
        raise HTTPException(status_code=404, detail="Beacon not found")
    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        setattr(beacon, k, v)
    await write_audit(session, actor.id, "beacon.updated", "ble_beacon", str(beacon.id), updates)
    await session.commit()
    await session.refresh(beacon)
    return _beacon_out(beacon)


@router.delete("/beacons/{beacon_id}")
async def delete_beacon(
    beacon_id: uuid.UUID,
    actor: Employee = Depends(require_role(3)),
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
