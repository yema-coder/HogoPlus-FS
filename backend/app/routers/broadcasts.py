"""v1.0.27 Broadcast / Send-Notification engine.

Reuses the EXISTING transport: the in-app inbox (notifications table) is the
source of truth — every recipient always gets a row — and Expo push is the
wake-up, now batched with per-recipient delivery tracking (broadcast_receipts).
Role-gated to MD / CGM / Time-Office. Real send/schedule is behind the
settings.broadcasts_enabled flag (preview + test-to-me always work).
"""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
    BleBeacon,
    Broadcast,
    BroadcastReceipt,
    Employee,
    FactorySettings,
    Notification,
    WorkerPresence,
)
from app.notify import expo_fetch_receipts, expo_send_messages
from app.redis_client import redis_client
from app.schemas import (
    BroadcastAudienceIn,
    BroadcastComposeIn,
    BroadcastOpenedIn,
    BroadcastResendIn,
)
from app.security import get_approved_employee, is_dept_manager
from app.shift_logic import now_ist

logger = logging.getLogger("hogo.broadcast")
router = APIRouter(tags=["broadcasts"])

PRIORITY_EMOJI = {"normal": "📢", "important": "❗", "emergency": "🚨"}


# ---------------- access + helpers ----------------

async def _require_broadcast_access(session: AsyncSession, actor: Employee) -> None:
    """MD / CGM (rank<=2) or a Time-Office manager. Everyone else 403."""
    if actor.role.rank <= 2:
        return
    if await is_dept_manager(session, actor, "TIME_OFFICE"):
        return
    raise HTTPException(status_code=403, detail="Send Notification is for MD / CGM / Time Office only")


async def _settings(session: AsyncSession) -> FactorySettings | None:
    return (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()


def _pick(*vals: str) -> str:
    for v in vals:
        if v and v.strip():
            return v.strip()
    return ""


def _lang_dict(mr: str, en: str, hi: str) -> dict:
    """Marathi-primary trilingual dict — an empty translation falls back to mr
    (then en, then hi) so no recipient ever sees a blank notification."""
    primary = _pick(mr, en, hi)
    return {
        "mr": _pick(mr, primary),
        "en": _pick(en, primary),
        "hi": _pick(hi, primary),
    }


def _titles(bc: Broadcast) -> dict:
    emoji = PRIORITY_EMOJI.get(bc.priority, "📢")
    base = _lang_dict(bc.title_mr, bc.title_en, bc.title_hi)
    return {k: f"{emoji} {v}".strip() for k, v in base.items()}


def _bodies(bc: Broadcast) -> dict:
    return _lang_dict(bc.body_mr, bc.body_en, bc.body_hi)


def _in_quiet_hours() -> bool:
    h = now_ist().hour
    return h >= 22 or h < 6


async def _resolve_recipients(
    session: AsyncSession, actor: Employee, data: BroadcastAudienceIn
) -> list[Employee]:
    """Resolve the audience to concrete employees, scoped to the actor's demo
    bubble, active + approved + has a phone, excluding the sender."""
    at = data.audience_type
    if at != "all":
        sel = {
            "department": data.departments,
            "role": data.roles,
            "designation": data.designations,
            "zone": data.zones,
            "employees": data.employee_ids,
        }[at]
        if not sel:
            return []
    q = select(Employee).where(
        Employee.is_active.is_(True),
        Employee.onboarding_status == "approved",
        Employee.is_demo.is_(actor.is_demo),
        Employee.id != actor.id,
        Employee.phone.isnot(None),
    )
    if at == "department":
        q = q.where(Employee.department_code.in_(data.departments or []))
    elif at == "role":
        q = q.where(Employee.role_code.in_(data.roles or []))
    elif at == "designation":
        q = q.where(Employee.designation.in_(data.designations or []))
    elif at == "employees":
        q = q.where(Employee.id.in_(data.employee_ids or []))
    elif at == "zone":
        sub = select(WorkerPresence.employee_id).where(
            WorkerPresence.zone_en.in_(data.zones or []),
            WorkerPresence.is_demo.is_(actor.is_demo),
        )
        q = q.where(Employee.id.in_(sub))
    return list((await session.execute(q)).scalars().all())


def _has_token(e: Employee) -> bool:
    return bool(e.expo_push_token and e.expo_push_token.startswith("ExponentPushToken"))


async def _send_push(bc: Broadcast, employees: list[Employee]) -> dict:
    """Batch-push to employees that have a token (quiet hours suppresses NORMAL
    pushes — inbox row still created). Returns {employee_id: (status, ticket, error)}."""
    quiet = _in_quiet_hours()
    titles, bodies = _titles(bc), _bodies(bc)
    result: dict[uuid.UUID, tuple[str, str | None, str | None]] = {}
    msgs: list[dict] = []
    order: list[uuid.UUID] = []
    for e in employees:
        if not _has_token(e):
            result[e.id] = ("no_token", None, None)
            continue
        if quiet and bc.priority == "normal":
            result[e.id] = ("suppressed", None, None)
            continue
        lang = e.language_pref or "mr"
        msgs.append(
            {
                "to": e.expo_push_token,
                "title": titles.get(lang, titles["mr"]),
                "body": bodies.get(lang, bodies["mr"]),
                "sound": "default",
                "priority": "high" if bc.priority in ("important", "emergency") else "default",
                "data": {
                    "type": "broadcast",
                    "broadcast_id": str(bc.id),
                    "entity_type": bc.deep_link_type or "broadcast",
                    "entity_id": bc.deep_link_id or str(bc.id),
                },
            }
        )
        order.append(e.id)
    tickets = await expo_send_messages(msgs)
    for eid, tk in zip(order, tickets):
        if tk.get("status") == "ok":
            result[eid] = ("sent", tk.get("id"), None)
        else:
            err = (tk.get("details") or {}).get("error") or tk.get("message") or "error"
            result[eid] = ("failed", None, str(err)[:200])
    return result


async def _recount(session: AsyncSession, bc: Broadcast) -> None:
    rows = (
        await session.execute(
            select(BroadcastReceipt.status, func.count())
            .where(BroadcastReceipt.broadcast_id == bc.id)
            .group_by(BroadcastReceipt.status)
        )
    ).all()
    counts = {s: c for s, c in rows}
    bc.sent_count = counts.get("sent", 0)
    bc.delivered_count = counts.get("delivered", 0)
    bc.failed_count = counts.get("failed", 0)
    bc.no_token_count = counts.get("no_token", 0)
    bc.suppressed_count = counts.get("suppressed", 0)
    bc.opened_count = counts.get("opened", 0)
    bc.installed_count = bc.sent_count + bc.delivered_count + bc.failed_count + bc.opened_count


async def _deliver(session: AsyncSession, bc: Broadcast, recipients: list[Employee]) -> None:
    """First-time delivery: create an inbox row for EVERY recipient, push to those
    with tokens, and record a receipt per recipient. Commits are the caller's job."""
    titles, bodies = _titles(bc), _bodies(bc)
    push = await _send_push(bc, recipients)
    for e in recipients:
        lang = e.language_pref or "mr"
        note = Notification(
            recipient_id=e.id,
            is_demo=bool(e.is_demo),
            type="broadcast",
            title_en=titles["en"], title_hi=titles["hi"], title_mr=titles["mr"],
            body_en=bodies["en"], body_hi=bodies["hi"], body_mr=bodies["mr"],
            entity_type=bc.deep_link_type or "broadcast",
            entity_id=bc.deep_link_id or str(bc.id),
        )
        session.add(note)
        await session.flush()
        status, ticket, error = push.get(e.id, ("no_token", None, None))
        if error == "DeviceNotRegistered":
            e.expo_push_token = None
            status = "no_token"
        session.add(
            BroadcastReceipt(
                broadcast_id=bc.id, employee_id=e.id, notification_id=note.id,
                ticket_id=ticket, status=status, error=error,
            )
        )
        _ = lang
    bc.recipient_count = len(recipients)
    bc.status = "sent"
    bc.sent_at = datetime.now(timezone.utc)
    await session.flush()
    await _recount(session, bc)


def _bc_out(bc: Broadcast, actor_name: str | None = None) -> dict:
    return {
        "id": str(bc.id),
        "created_by": str(bc.created_by),
        "created_by_name": actor_name,
        "audience_type": bc.audience_type,
        "audience_json": bc.audience_json,
        "title_en": bc.title_en, "title_hi": bc.title_hi, "title_mr": bc.title_mr,
        "body_en": bc.body_en, "body_hi": bc.body_hi, "body_mr": bc.body_mr,
        "priority": bc.priority,
        "deep_link_type": bc.deep_link_type,
        "deep_link_id": bc.deep_link_id,
        "scheduled_at": bc.scheduled_at.isoformat() if bc.scheduled_at else None,
        "status": bc.status,
        "sent_at": bc.sent_at.isoformat() if bc.sent_at else None,
        "recipient_count": bc.recipient_count,
        "installed_count": bc.installed_count,
        "sent_count": bc.sent_count,
        "delivered_count": bc.delivered_count,
        "failed_count": bc.failed_count,
        "no_token_count": bc.no_token_count,
        "suppressed_count": bc.suppressed_count,
        "opened_count": bc.opened_count,
        "is_test": bc.is_test,
        "created_at": bc.created_at.isoformat() if bc.created_at else None,
    }


def _text_hash(body: BroadcastComposeIn) -> str:
    raw = f"{body.title_mr}|{body.title_en}|{body.title_hi}|{body.body_mr}|{body.body_en}|{body.body_hi}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------- endpoints ----------------

@router.get("/broadcasts/meta")
async def broadcast_meta(
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    s = await _settings(session)
    zones = (
        await session.execute(
            select(BleBeacon.zone_label_en)
            .where(BleBeacon.is_active.is_(True), BleBeacon.zone_label_en != "")
            .distinct()
            .order_by(BleBeacon.zone_label_en)
        )
    ).scalars().all()
    return {
        "enabled": bool(s.broadcasts_enabled) if s else False,
        "rate_per_hour": int(s.broadcast_rate_per_hour) if s else 10,
        "zones": list(zones),
    }


@router.post("/broadcasts/preview")
async def broadcast_preview(
    body: BroadcastAudienceIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    recipients = await _resolve_recipients(session, actor, body)
    installed = sum(1 for e in recipients if _has_token(e))
    return {
        "recipient_count": len(recipients),
        "installed_count": installed,
        "no_token_count": len(recipients) - installed,
    }


async def _check_rate_and_dup(
    session: AsyncSession, actor: Employee, body: BroadcastComposeIn
) -> None:
    s = await _settings(session)
    limit = int(s.broadcast_rate_per_hour) if s else 10
    bucket = now_ist().strftime("%Y%m%d%H")
    key = f"broadcast:rate:{int(actor.is_demo)}:{bucket}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 3700)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail={"code": "broadcast_rate_limited", "limit": limit,
                        "message": f"Broadcast limit reached ({limit}/hour). Try again later."},
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — redis blip must not block a real broadcast
        pass
    if not body.force:
        dkey = f"broadcast:dup:{int(actor.is_demo)}"
        try:
            last = await redis_client.get(dkey)
            if last == _text_hash(body):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "duplicate_recent",
                            "message": "The same message was sent in the last 30 minutes. Send again?"},
                )
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass


async def _remember_text(actor: Employee, body: BroadcastComposeIn) -> None:
    try:
        await redis_client.set(f"broadcast:dup:{int(actor.is_demo)}", _text_hash(body), ex=1800)
    except Exception:  # noqa: BLE001
        pass


@router.post("/broadcasts")
async def create_broadcast(
    body: BroadcastComposeIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    s = await _settings(session)
    if not (s and s.broadcasts_enabled):
        raise HTTPException(status_code=403, detail={"code": "broadcasts_disabled",
                            "message": "Send Notification is switched off. Enable it in Admin first."})
    scheduled = body.scheduled_at
    now_utc = datetime.now(timezone.utc)
    is_future = bool(scheduled and scheduled > now_utc + timedelta(seconds=30))

    bc = Broadcast(
        created_by=actor.id,
        audience_type=body.audience_type,
        audience_json={
            "departments": body.departments, "roles": body.roles,
            "designations": body.designations, "zones": body.zones,
            "employee_ids": [str(x) for x in body.employee_ids] if body.employee_ids else None,
        },
        title_en=body.title_en, title_hi=body.title_hi, title_mr=body.title_mr,
        body_en=body.body_en, body_hi=body.body_hi, body_mr=body.body_mr,
        priority=body.priority,
        deep_link_type=body.deep_link_type, deep_link_id=body.deep_link_id,
        scheduled_at=scheduled if is_future else None,
        is_demo=actor.is_demo,
    )

    if is_future:
        # Validate the audience resolves to someone, but defer the actual send to
        # the per-minute scheduler sweep (survives a backend restart — state is DB).
        bc.status = "scheduled"
        bc.recipient_count = len(await _resolve_recipients(session, actor, body))
        session.add(bc)
        await session.flush()
        await write_audit(session, actor.id, "broadcast.scheduled", "broadcast", str(bc.id),
                          {"audience": body.audience_type, "when": scheduled.isoformat()})
        await session.commit()
        await session.refresh(bc)
        return _bc_out(bc, actor.full_name)

    await _check_rate_and_dup(session, actor, body)
    recipients = await _resolve_recipients(session, actor, body)
    if not recipients:
        raise HTTPException(status_code=422, detail={"code": "no_recipients",
                            "message": "This audience has no one to notify."})
    session.add(bc)
    await session.flush()
    await _deliver(session, bc, recipients)
    await write_audit(session, actor.id, "broadcast.sent", "broadcast", str(bc.id),
                      {"audience": body.audience_type, "priority": body.priority,
                       "recipients": bc.recipient_count, "title": _pick(body.title_mr, body.title_en)})
    await session.commit()
    await session.refresh(bc)
    await _remember_text(actor, body)
    logger.info("broadcast %s sent → %d recipients (%d push)", bc.id, bc.recipient_count, bc.installed_count)
    return _bc_out(bc, actor.full_name)


@router.post("/broadcasts/test")
async def test_broadcast(
    body: BroadcastComposeIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Send ONLY to the composer — always allowed, even when the flag is OFF, so
    they can verify the message on their own phone before broadcasting."""
    await _require_broadcast_access(session, actor)
    bc = Broadcast(
        created_by=actor.id, audience_type="employees",
        audience_json={"employee_ids": [str(actor.id)]},
        title_en=body.title_en, title_hi=body.title_hi, title_mr=body.title_mr,
        body_en=body.body_en, body_hi=body.body_hi, body_mr=body.body_mr,
        priority=body.priority,
        deep_link_type=body.deep_link_type, deep_link_id=body.deep_link_id,
        is_test=True, is_demo=actor.is_demo,
    )
    session.add(bc)
    await session.flush()
    await _deliver(session, bc, [actor])
    await session.commit()
    await session.refresh(bc)
    return _bc_out(bc, actor.full_name)


@router.get("/broadcasts")
async def list_broadcasts(
    type: str | None = None,
    department: str | None = None,
    q: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    query = (
        select(Broadcast, Employee.full_name)
        .join(Employee, Employee.id == Broadcast.created_by, isouter=True)
        .where(Broadcast.is_demo.is_(actor.is_demo), Broadcast.is_test.is_(False))
        .order_by(Broadcast.created_at.desc())
        .limit(200)
    )
    if type:
        query = query.where(Broadcast.priority == type)
    rows = (await session.execute(query)).all()
    out = []
    for bc, name in rows:
        if department and (bc.audience_type != "department"
                           or department not in (bc.audience_json.get("departments") or [])):
            continue
        if q:
            hay = f"{bc.title_mr} {bc.title_en} {bc.title_hi} {bc.body_mr} {bc.body_en} {bc.body_hi}".lower()
            if q.lower() not in hay:
                continue
        out.append(_bc_out(bc, name))
    return {"items": out}


@router.get("/broadcasts/{broadcast_id}")
async def broadcast_detail(
    broadcast_id: uuid.UUID,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None or bc.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    creator = await session.get(Employee, bc.created_by)
    failed = (
        await session.execute(
            select(BroadcastReceipt, Employee.full_name, Employee.emp_id, Employee.department_code)
            .join(Employee, Employee.id == BroadcastReceipt.employee_id)
            .where(
                BroadcastReceipt.broadcast_id == bc.id,
                BroadcastReceipt.status.in_(("failed", "no_token")),
            )
            .limit(100)
        )
    ).all()
    out = _bc_out(bc, creator.full_name if creator else None)
    out["failed_recipients"] = [
        {"emp_id": eid, "name": name, "department_code": dept,
         "status": r.status, "error": r.error}
        for r, name, eid, dept in failed
    ]
    return out


@router.post("/broadcasts/{broadcast_id}/resend")
async def resend_broadcast(
    broadcast_id: uuid.UUID,
    body: BroadcastResendIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    await _require_broadcast_access(session, actor)
    s = await _settings(session)
    if not (s and s.broadcasts_enabled):
        raise HTTPException(status_code=403, detail={"code": "broadcasts_disabled",
                            "message": "Send Notification is switched off."})
    bc = await session.get(Broadcast, broadcast_id)
    if bc is None or bc.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    rq = select(BroadcastReceipt).where(BroadcastReceipt.broadcast_id == bc.id)
    if body.failed_only:
        rq = rq.where(BroadcastReceipt.status.in_(("failed", "no_token")))
    receipts = {r.employee_id: r for r in (await session.execute(rq)).scalars().all()}
    if not receipts:
        return _bc_out(bc, actor.full_name)
    emps = (
        await session.execute(select(Employee).where(Employee.id.in_(list(receipts.keys()))))
    ).scalars().all()
    push = await _send_push(bc, emps)
    for e in emps:
        status, ticket, error = push.get(e.id, ("no_token", None, None))
        if error == "DeviceNotRegistered":
            e.expo_push_token = None
            status = "no_token"
        r = receipts[e.id]
        r.status, r.ticket_id, r.error = status, ticket, error
    await session.flush()
    await _recount(session, bc)
    await write_audit(session, actor.id, "broadcast.resent", "broadcast", str(bc.id),
                      {"failed_only": body.failed_only, "targets": len(emps)})
    await session.commit()
    await session.refresh(bc)
    return _bc_out(bc, actor.full_name)


@router.post("/broadcasts/receipt-opened")
async def mark_opened(
    body: BroadcastOpenedIn,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Called by the mobile app when a broadcast push is tapped (built apps only)."""
    r = (
        await session.execute(
            select(BroadcastReceipt).where(
                BroadcastReceipt.broadcast_id == body.broadcast_id,
                BroadcastReceipt.employee_id == actor.id,
            )
        )
    ).scalar_one_or_none()
    if r and r.status != "opened":
        r.status = "opened"
        bc = await session.get(Broadcast, body.broadcast_id)
        if bc:
            await _recount(session, bc)
        await session.commit()
    return {"ok": True}


# ---------------- scheduler-callable sweeps ----------------

async def run_broadcast_schedule_sweep() -> dict:
    """Send any scheduled broadcasts whose time has arrived. DB-state driven, so
    a backend restart never loses a scheduled send."""
    from app.database import get_session as _gs

    now_utc = datetime.now(timezone.utc)
    sent = 0
    async for session in _gs():
        due = (
            await session.execute(
                select(Broadcast).where(
                    Broadcast.status == "scheduled",
                    Broadcast.scheduled_at.isnot(None),
                    Broadcast.scheduled_at <= now_utc,
                ).limit(20)
            )
        ).scalars().all()
        for bc in due:
            bc.status = "sending"
            await session.flush()
            actor = await session.get(Employee, bc.created_by)
            if actor is None:
                bc.status = "failed"
                continue
            data = BroadcastAudienceIn(
                audience_type=bc.audience_type,
                departments=(bc.audience_json or {}).get("departments"),
                roles=(bc.audience_json or {}).get("roles"),
                designations=(bc.audience_json or {}).get("designations"),
                zones=(bc.audience_json or {}).get("zones"),
                employee_ids=[uuid.UUID(x) for x in (bc.audience_json or {}).get("employee_ids") or []]
                if (bc.audience_json or {}).get("employee_ids") else None,
            )
            recipients = await _resolve_recipients(session, actor, data)
            await _deliver(session, bc, recipients)
            await write_audit(session, actor.id, "broadcast.sent_scheduled", "broadcast", str(bc.id),
                              {"recipients": bc.recipient_count})
            sent += 1
        if due:
            await session.commit()
    return {"scheduled_sent": sent}


async def run_broadcast_receipt_sweep() -> dict:
    """Poll Expo for receipts on recently-sent pushes → delivered/failed, and
    clean up tokens that Expo reports as DeviceNotRegistered."""
    from app.database import get_session as _gs

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    updated = 0
    async for session in _gs():
        pending = (
            await session.execute(
                select(BroadcastReceipt).where(
                    BroadcastReceipt.status == "sent",
                    BroadcastReceipt.ticket_id.isnot(None),
                    BroadcastReceipt.updated_at <= cutoff,
                ).limit(900)
            )
        ).scalars().all()
        if not pending:
            return {"receipts_checked": 0}
        by_ticket = {r.ticket_id: r for r in pending}
        receipts = await expo_fetch_receipts(list(by_ticket.keys()))
        touched: set[uuid.UUID] = set()
        for tid, rec in receipts.items():
            r = by_ticket.get(tid)
            if not r:
                continue
            if rec.get("status") == "ok":
                r.status = "delivered"
            else:
                err = (rec.get("details") or {}).get("error") or rec.get("message") or "error"
                r.status = "failed"
                r.error = str(err)[:200]
                if err == "DeviceNotRegistered":
                    emp = await session.get(Employee, r.employee_id)
                    if emp:
                        emp.expo_push_token = None
                    r.status = "no_token"
            touched.add(r.broadcast_id)
            updated += 1
        for bid in touched:
            bc = await session.get(Broadcast, bid)
            if bc:
                await _recount(session, bc)
        await session.commit()
    return {"receipts_updated": updated}
