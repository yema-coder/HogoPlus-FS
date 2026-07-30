import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import Department, Employee, Shift, ShiftAssignment, ShiftSwapRequest
from app.notify import dispatcher, template
from app.schemas import SwapCreateIn, SwapDecideIn, SwapRespondIn
from app.security import get_approved_employee, is_dept_manager, require_role
from app.shift_logic import now_ist, resolve_shift_code

router = APIRouter(tags=["shifts"])


def _swap_out(s: ShiftSwapRequest) -> dict:
    return {
        "id": str(s.id),
        "requester_id": str(s.requester_id),
        "target_id": str(s.target_id),
        "swap_date": s.swap_date.isoformat(),
        "status": s.status,
        "target_responded_at": s.target_responded_at.isoformat() if s.target_responded_at else None,
        "manager_id": str(s.manager_id) if s.manager_id else None,
        "manager_responded_at": s.manager_responded_at.isoformat() if s.manager_responded_at else None,
        "reason": s.reason,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


async def _swap_out_full(session: AsyncSession, s: ShiftSwapRequest) -> dict:
    """Swap payload enriched with both employees' names + shift codes (mobile approval cards)."""
    out = _swap_out(s)
    requester = await session.get(Employee, s.requester_id)
    target = await session.get(Employee, s.target_id)
    out["requester_name"] = requester.full_name if requester else None
    out["requester_emp_id"] = requester.emp_id if requester else None
    out["target_name"] = target.full_name if target else None
    out["target_emp_id"] = target.emp_id if target else None
    out["department_code"] = requester.department_code if requester else None
    out["requester_shift_code"] = await resolve_shift_code(session, s.requester_id, s.swap_date)
    out["target_shift_code"] = await resolve_shift_code(session, s.target_id, s.swap_date)
    return out


@router.get("/shifts/mine")
async def my_shifts(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    shifts = {s.code: s for s in (await session.execute(select(Shift))).scalars().all()}
    today = now_ist().date()
    out = []
    for offset in range(8):
        d = today + timedelta(days=offset)
        code = await resolve_shift_code(session, employee.id, d)
        shift = shifts.get(code) if code else None
        out.append(
            {
                "date": d.isoformat(),
                "shift_code": code,
                "label": shift.label if shift else None,
                "start_time": shift.start_time.isoformat() if shift else None,
                "end_time": shift.end_time.isoformat() if shift else None,
            }
        )
    return out


@router.get("/shifts/roster")
async def roster(
    department_code: str,
    date: str | None = Query(default=None),
    employee: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    target = datetime.fromisoformat(date).date() if date else now_ist().date()
    employees = (
        await session.execute(
            select(Employee).where(Employee.department_code == department_code, Employee.is_active.is_(True))
        )
    ).scalars().all()
    out = []
    for emp in employees:
        code = await resolve_shift_code(session, emp.id, target)
        out.append(
            {
                "employee_id": str(emp.id),
                "emp_id": emp.emp_id,
                "full_name": emp.full_name,
                "designation": emp.designation,
                "shift_code": code,
            }
        )
    return {"department_code": department_code, "date": target.isoformat(), "roster": out}


@router.get("/shift-swaps/candidates")
async def swap_candidates(
    date: str = Query(...),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Same-department, swap-eligible colleagues on a DIFFERENT shift for the given date.
    Accessible to any eligible employee (roster stays Manager+ only)."""
    if not employee.shift_swap_eligible:
        raise HTTPException(status_code=403, detail="Not shift-swap eligible")
    try:
        target_date = datetime.fromisoformat(date).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if target_date < now_ist().date():
        raise HTTPException(status_code=400, detail="Date cannot be in the past")

    my_shift = await resolve_shift_code(session, employee.id, target_date)
    candidates = []
    if my_shift:
        colleagues = (
            await session.execute(
                select(Employee).where(
                    Employee.department_code == employee.department_code,
                    Employee.is_active.is_(True),
                    Employee.shift_swap_eligible.is_(True),
                    Employee.onboarding_status == "approved",
                    Employee.is_demo == employee.is_demo,
                    Employee.id != employee.id,
                )
            )
        ).scalars().all()
        for emp in colleagues:
            code = await resolve_shift_code(session, emp.id, target_date)
            if code and code != my_shift:
                candidates.append(
                    {
                        "employee_id": str(emp.id),
                        "emp_id": emp.emp_id,
                        "full_name": emp.full_name,
                        "shift_code": code,
                    }
                )
    return {"date": target_date.isoformat(), "my_shift_code": my_shift, "candidates": candidates}


@router.post("/shift-swaps")
async def create_swap(
    body: SwapCreateIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(Employee, body.target_employee_id)
    if target is None or not target.is_active or target.is_demo != employee.is_demo:
        raise HTTPException(status_code=404, detail="Target employee not found")
    if target.id == employee.id:
        raise HTTPException(status_code=400, detail="Cannot swap with yourself")
    if not employee.shift_swap_eligible or not target.shift_swap_eligible:
        raise HTTPException(status_code=400, detail="Both employees must be shift-swap eligible")
    if employee.department_code != target.department_code:
        raise HTTPException(status_code=400, detail="Swap allowed only within the same department")
    if body.swap_date < now_ist().date():
        raise HTTPException(status_code=400, detail="Swap date cannot be in the past")

    my_shift = await resolve_shift_code(session, employee.id, body.swap_date)
    their_shift = await resolve_shift_code(session, target.id, body.swap_date)
    if not my_shift or not their_shift:
        raise HTTPException(status_code=400, detail="Both employees must have a shift on the swap date")
    if my_shift == their_shift:
        raise HTTPException(status_code=400, detail="Both employees are on the same shift that day")

    swap = ShiftSwapRequest(
        requester_id=employee.id,
        target_id=target.id,
        is_demo=employee.is_demo,
        swap_date=body.swap_date,
        reason=body.reason,
        status="pending_target",
    )
    session.add(swap)
    await session.flush()
    title, notif_body = template("swap_request", f"{employee.full_name} → {body.swap_date.isoformat()}")
    await dispatcher.notify(session, target.id, "swap_request", title, notif_body, "shift_swap", str(swap.id))
    await write_audit(session, employee.id, "shift_swap.created", "shift_swap", str(swap.id), {"swap_date": body.swap_date.isoformat()})
    await session.commit()
    await session.refresh(swap)
    return await _swap_out_full(session, swap)


@router.post("/shift-swaps/{swap_id}/respond")
async def respond_swap(
    swap_id: uuid.UUID,
    body: SwapRespondIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    # FOR UPDATE: serialize concurrent respond/decide/cancel on the same swap —
    # the status check below then sees the committed truth, never a stale read
    swap = await session.get(ShiftSwapRequest, swap_id, with_for_update=True)
    if swap is None:
        raise HTTPException(status_code=404, detail="Swap request not found")
    if swap.target_id != employee.id:
        raise HTTPException(status_code=403, detail="Only the target employee can respond")
    if swap.status != "pending_target":
        raise HTTPException(status_code=409, detail=f"Swap is {swap.status}")

    swap.target_responded_at = datetime.now(timezone.utc)
    if body.accept:
        swap.status = "pending_manager"
        # notify department manager (or CGM)
        dept = (
            await session.execute(select(Department).where(Department.code == employee.department_code))
        ).scalar_one_or_none()
        from app.demo import get_role_holder, resolve_dept_manager_id

        recipient = await resolve_dept_manager_id(session, dept, employee.is_demo)
        if recipient is None:
            cgm = await get_role_holder(session, "CGM", employee.is_demo)
            recipient = cgm.id if cgm else None
        if recipient:
            title, notif_body = template("swap_manager_pending", f"{swap.swap_date.isoformat()}")
            await dispatcher.notify(session, recipient, "swap_manager_pending", title, notif_body, "shift_swap", str(swap.id))
    else:
        swap.status = "rejected"
    await write_audit(
        session, employee.id, "shift_swap.target_response", "shift_swap", str(swap.id),
        {"accepted": body.accept},
    )
    await session.commit()
    await session.refresh(swap)
    return await _swap_out_full(session, swap)


@router.post("/shift-swaps/{swap_id}/decide")
async def decide_swap(
    swap_id: uuid.UUID,
    body: SwapDecideIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    swap = await session.get(ShiftSwapRequest, swap_id, with_for_update=True)
    if swap is None or swap.is_demo != employee.is_demo:
        raise HTTPException(status_code=404, detail="Swap request not found")
    requester = await session.get(Employee, swap.requester_id)
    if not await is_dept_manager(session, employee, requester.department_code):
        raise HTTPException(status_code=403, detail="Only the department Manager (or CGM/MD) can decide")
    if swap.status != "pending_manager":
        raise HTTPException(status_code=409, detail=f"Swap is {swap.status}")

    swap.manager_id = employee.id
    swap.manager_responded_at = datetime.now(timezone.utc)

    if body.approve:
        swap.status = "approved"
        req_shift = await resolve_shift_code(session, swap.requester_id, swap.swap_date)
        tgt_shift = await resolve_shift_code(session, swap.target_id, swap.swap_date)
        for emp_id, new_code in ((swap.requester_id, tgt_shift), (swap.target_id, req_shift)):
            existing = (
                await session.execute(
                    select(ShiftAssignment).where(
                        ShiftAssignment.employee_id == emp_id,
                        ShiftAssignment.effective_date == swap.swap_date,
                        ShiftAssignment.source == "swap",
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.shift_code = new_code
            else:
                session.add(
                    ShiftAssignment(
                        employee_id=emp_id, shift_code=new_code,
                        effective_date=swap.swap_date, source="swap",
                    )
                )
        # both sides to audit_events
        detail = {
            "swap_id": str(swap.id), "swap_date": swap.swap_date.isoformat(),
            "requester_shift": f"{req_shift}->{tgt_shift}", "target_shift": f"{tgt_shift}->{req_shift}",
        }
        await write_audit(session, employee.id, "shift_swap.applied", "employee", str(swap.requester_id), detail)
        await write_audit(session, employee.id, "shift_swap.applied", "employee", str(swap.target_id), detail)
    else:
        swap.status = "rejected"
        swap.reason = body.reason or swap.reason

    await write_audit(
        session, employee.id,
        "shift_swap.approved" if body.approve else "shift_swap.rejected",
        "shift_swap", str(swap.id), {"reason": body.reason},
    )
    decision_txt = "approved" if body.approve else f"rejected: {body.reason or ''}"
    for recipient in (swap.requester_id, swap.target_id):
        title, notif_body = template("swap_decided", decision_txt)
        await dispatcher.notify(session, recipient, "swap_decided", title, notif_body, "shift_swap", str(swap.id))
    await session.commit()
    await session.refresh(swap)
    return await _swap_out_full(session, swap)


@router.post("/shift-swaps/{swap_id}/cancel")
async def cancel_swap(
    swap_id: uuid.UUID,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    swap = await session.get(ShiftSwapRequest, swap_id, with_for_update=True)
    if swap is None:
        raise HTTPException(status_code=404, detail="Swap request not found")
    if swap.requester_id != employee.id:
        raise HTTPException(status_code=403, detail="Only the requester can cancel")
    if swap.status not in ("pending_target", "pending_manager"):
        raise HTTPException(status_code=409, detail=f"Swap is {swap.status}")
    swap.status = "cancelled"
    await write_audit(session, employee.id, "shift_swap.cancelled", "shift_swap", str(swap.id), {})
    await session.commit()
    await session.refresh(swap)
    return await _swap_out_full(session, swap)


@router.get("/shift-swaps/mine")
async def my_swaps(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(ShiftSwapRequest)
            .where((ShiftSwapRequest.requester_id == employee.id) | (ShiftSwapRequest.target_id == employee.id))
            .order_by(ShiftSwapRequest.created_at.desc())
        )
    ).scalars().all()
    return [await _swap_out_full(session, s) for s in rows]


@router.get("/shift-swaps/pending")
async def pending_swaps(
    employee: Employee = Depends(require_role(3)),
    session: AsyncSession = Depends(get_session),
):
    query = select(ShiftSwapRequest).where(
        ShiftSwapRequest.status == "pending_manager",
        ShiftSwapRequest.is_demo == employee.is_demo,
    )
    if employee.role.rank == 3:
        query = query.join(Employee, ShiftSwapRequest.requester_id == Employee.id).where(
            Employee.department_code == employee.department_code
        )
    rows = (await session.execute(query.order_by(ShiftSwapRequest.created_at.desc()))).scalars().all()
    return [await _swap_out_full(session, s) for s in rows]
