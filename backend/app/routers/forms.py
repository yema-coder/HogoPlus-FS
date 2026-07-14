import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.form_validation import validate_submission
from app.models import Department, Employee, FormDefinition, FormSubmission
from app.notify import dispatcher, template
from app.schemas import FormSubmitIn, RejectIn
from app.security import get_approved_employee, is_dept_manager

router = APIRouter(tags=["forms"])


def _def_out(d: FormDefinition) -> dict:
    return {
        "id": str(d.id),
        "department_code": d.department_code,
        "code": d.code,
        "title_en": d.title_en,
        "title_hi": d.title_hi,
        "title_mr": d.title_mr,
        "schema_json": d.schema_json,
        "version": d.version,
        "is_active": d.is_active,
        "requires_approval": d.requires_approval,
        "approval_role_code": d.approval_role_code,
    }


def _sub_out(s: FormSubmission, form_code: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "form_definition_id": str(s.form_definition_id),
        "form_code": form_code,
        "form_version": s.form_version,
        "submitted_by": str(s.submitted_by),
        "department_code": s.department_code,
        "data_json": s.data_json,
        "photos": s.photos,
        "gps_lat": s.gps_lat,
        "gps_lng": s.gps_lng,
        "status": s.status,
        "approver_id": str(s.approver_id) if s.approver_id else None,
        "approved_at": s.approved_at.isoformat() if s.approved_at else None,
        "rejection_reason": s.rejection_reason,
        "escalated_to": str(s.escalated_to) if s.escalated_to else None,
        "escalated_at": s.escalated_at.isoformat() if s.escalated_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/forms")
async def list_forms(
    department_code: str | None = Query(default=None),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    # Workers/Staff/Clerks see only their own department's forms; Manager+ can view any
    if employee.role.rank > 3 or department_code is None:
        dept = employee.department_code if employee.role.rank > 3 else (department_code or employee.department_code)
    else:
        dept = department_code
    defs = (
        await session.execute(
            select(FormDefinition)
            .where(FormDefinition.department_code == dept, FormDefinition.is_active.is_(True))
            .order_by(FormDefinition.code)
        )
    ).scalars().all()
    return [_def_out(d) for d in defs]


@router.post("/forms/{definition_id}/submit")
async def submit_form(
    definition_id: uuid.UUID,
    body: FormSubmitIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    definition = await session.get(FormDefinition, definition_id)
    if definition is None or not definition.is_active:
        raise HTTPException(status_code=404, detail="Form not found")
    if employee.role.rank > 3 and definition.department_code != employee.department_code:
        raise HTTPException(status_code=403, detail="You can only submit forms of your own department")

    errors = validate_submission(body.data_json, definition.schema_json)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    submission = FormSubmission(
        form_definition_id=definition.id,
        form_version=definition.version,
        submitted_by=employee.id,
        department_code=definition.department_code,
        data_json=body.data_json,
        photos=body.photos,
        gps_lat=body.gps_lat,
        gps_lng=body.gps_lng,
        status="submitted" if definition.requires_approval else "approved",
    )
    session.add(submission)
    await session.flush()

    if definition.requires_approval:
        dept = (
            await session.execute(select(Department).where(Department.code == definition.department_code))
        ).scalar_one_or_none()
        recipient = dept.manager_employee_id if dept else None
        if recipient is None:
            cgm = (
                await session.execute(
                    select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
                )
            ).scalar_one_or_none()
            recipient = cgm.id if cgm else None
        if recipient:
            title, notif_body = template("submission_pending", f"{definition.title_en} — {employee.full_name}")
            await dispatcher.notify(
                session, recipient, "submission_pending", title, notif_body,
                "form_submission", str(submission.id),
            )
    await session.commit()
    await session.refresh(submission)
    return _sub_out(submission, definition.code)


async def _decide(
    submission_id: uuid.UUID,
    approve: bool,
    reason: str | None,
    employee: Employee,
    session: AsyncSession,
) -> dict:
    submission = await session.get(FormSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not await is_dept_manager(session, employee, submission.department_code):
        raise HTTPException(status_code=403, detail="Only the department Manager (or CGM/MD) can decide")
    if submission.status not in ("submitted", "escalated"):
        raise HTTPException(status_code=409, detail=f"Submission already {submission.status}")

    submission.approver_id = employee.id
    submission.approved_at = datetime.now(timezone.utc)
    if approve:
        submission.status = "approved"
    else:
        submission.status = "rejected"
        submission.rejection_reason = reason

    action = "form_submission.approved" if approve else "form_submission.rejected"
    await write_audit(session, employee.id, action, "form_submission", str(submission.id), {"reason": reason})
    title, notif_body = template("submission_decided", "Approved" if approve else f"Rejected: {reason}")
    await dispatcher.notify(
        session, submission.submitted_by, "submission_decided", title, notif_body,
        "form_submission", str(submission.id),
    )
    await session.commit()
    await session.refresh(submission)
    return _sub_out(submission)


@router.post("/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: uuid.UUID,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    return await _decide(submission_id, True, None, employee, session)


@router.post("/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: uuid.UUID,
    body: RejectIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    return await _decide(submission_id, False, body.reason, employee, session)


@router.get("/submissions")
async def list_submissions(
    department_code: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    query = select(FormSubmission)
    rank = employee.role.rank
    if rank <= 2:
        if department_code:
            query = query.where(FormSubmission.department_code == department_code)
    elif rank == 3:
        query = query.where(FormSubmission.department_code == employee.department_code)
    else:
        query = query.where(FormSubmission.submitted_by == employee.id)

    if status:
        query = query.where(FormSubmission.status == status)
    if date_from:
        query = query.where(FormSubmission.created_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to:
        query = query.where(FormSubmission.created_at <= datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc))

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            query.order_by(FormSubmission.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {"items": [_sub_out(s) for s in rows], "total": total, "page": page, "page_size": page_size}
