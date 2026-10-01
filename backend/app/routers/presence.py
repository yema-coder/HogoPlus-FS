"""v1.0.25 LIVE WORKER PRESENCE — Phase 1 (flag-gated OFF by default).

A worker is tracked ONLY when ALL of:
  settings.live_presence_enabled  AND  emp_id in settings.presence_pilot_emp_ids
  AND a presence_consents row for CONSENT_VERSION  AND  punched in right now.
Zero tracking outside a shift — the server refuses pings, the client stops.

Honesty rules (owner-mandated):
  freshness = Live <=6 min | Recent <=15 min | Stale >15 min (5-min heartbeat)
  computed from server receive time; queued offline pings older than 3 min keep
  their own timestamp so history never masquerades as live.
  Punched-in but not in pilot / no consent  -> "not_tracked" (never "no signal")
  Worker stopped the service / denied perms -> "stopped"    (never "no signal")
"""
import math
import uuid as uuid_mod
from datetime import date as date_cls, datetime, time as time_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
    Attendance,
    BleBeacon,
    Employee,
    FactorySettings,
    PresenceAlert,
    PresenceConsent,
    PresenceHistory,
    WorkerPresence,
)
from app.presence_alerts import OPEN_STATUSES
from app.redis_client import redis_client
from app.schemas import PresenceConsentIn, PresencePingBatchIn, PresenceSettingsIn
from app.security import get_approved_employee, require_real_role, require_role
from app.shift_logic import get_shift, now_ist

router = APIRouter(prefix="/presence", tags=["presence"])

CONSENT_VERSION = "1.0"
LIVE_S = 6 * 60        # <= 6 min  -> Live   (5-min heartbeat + 1 min grace)
RECENT_S = 15 * 60     # <= 15 min -> Recent; beyond -> Stale == no_signal
OFFLINE_CATCHUP_S = 180  # queued pings older than this keep client_ts (history, not live)
PING_MIN_GAP_S = 20    # rate limit: one batch per 20s per worker
GAP_CAP_S = 600        # Phase 2: one ping "covers" at most 10 min (2× heartbeat)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _pilot_set(fs: FactorySettings) -> set[str]:
    return {s.strip() for s in (fs.presence_pilot_emp_ids or "").split(",") if s.strip()}


async def _settings(session: AsyncSession) -> FactorySettings:
    fs = (await session.execute(select(FactorySettings))).scalars().first()
    if fs is None:
        raise HTTPException(status_code=503, detail="Settings not seeded")
    return fs


async def _has_consent(session: AsyncSession, employee_id) -> bool:
    row = (
        await session.execute(
            select(PresenceConsent.id).where(
                PresenceConsent.employee_id == employee_id,
                PresenceConsent.version == CONSENT_VERSION,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _punched_in(session: AsyncSession, employee_id) -> bool:
    row = (
        await session.execute(
            select(Attendance.id).where(
                Attendance.employee_id == employee_id,
                Attendance.date == now_ist().date(),
                Attendance.punch_out_at.is_(None),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _zone_lookup(session: AsyncSession) -> dict[str, BleBeacon]:
    """Registry indexed by both key styles: 'uuid:major:minor' and 'mac:<MAC>'."""
    out: dict[str, BleBeacon] = {}
    for b in (await session.execute(select(BleBeacon).where(BleBeacon.is_active.is_(True)))).scalars():
        if b.beacon_uuid is not None and b.major is not None and b.minor is not None:
            out[f"{b.beacon_uuid.lower()}:{b.major}:{b.minor}"] = b
        if b.mac_address:
            out[f"mac:{b.mac_address.lower()}"] = b
    return out


# ---------------------------------------------------------------- worker side

@router.post("/consent")
async def record_consent(
    body: PresenceConsentIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    if body.version != CONSENT_VERSION:
        raise HTTPException(status_code=400, detail=f"Current consent version is {CONSENT_VERSION}")
    if not await _has_consent(session, employee.id):
        session.add(PresenceConsent(
            employee_id=employee.id, version=body.version, lang=body.lang, granted_at=now_ist(),
        ))
        await write_audit(
            session, employee.id, "presence.consent_granted", "employee", str(employee.id),
            {"version": body.version, "lang": body.lang}, is_demo=employee.is_demo,
        )
        await session.commit()
    return {"status": "consented", "version": CONSENT_VERSION}


@router.get("/my-status")
async def my_status(
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Everything the app needs at punch-in: is this worker in the tracking
    programme, is consent still needed, and the battery-friendly intervals."""
    fs = await _settings(session)
    in_pilot = employee.emp_id in _pilot_set(fs)
    consented = await _has_consent(session, employee.id)
    att = (
        await session.execute(
            select(Attendance).where(
                Attendance.employee_id == employee.id,
                Attendance.date == now_ist().date(),
                Attendance.punch_out_at.is_(None),
            ).limit(1)
        )
    ).scalars().first()
    punched_in = att is not None
    # honest auto-stop: shift end + 30 min grace (client stops itself; the server
    # keeps refusing pings after punch-out regardless)
    stop_after = None
    if att is not None and att.shift_code:
        sh = await get_shift(session, att.shift_code)
        if sh is not None:
            end_dt = datetime.combine(att.date, sh.end_time, tzinfo=now_ist().tzinfo)
            if sh.end_time <= sh.start_time:
                end_dt += timedelta(days=1)  # overnight shift ends tomorrow
            stop_after = (end_dt + timedelta(minutes=30)).isoformat()
    eligible = fs.live_presence_enabled and in_pilot
    me = (
        await session.execute(select(WorkerPresence).where(WorkerPresence.employee_id == employee.id))
    ).scalar_one_or_none()
    return {
        "enabled": fs.live_presence_enabled,
        "in_pilot": in_pilot,
        "consent_required": eligible and not consented,
        "consent_version": CONSENT_VERSION,
        "tracking_expected": eligible and consented and punched_in,
        "stop_after": stop_after,
        "intervals": {"scan_s": 90, "heartbeat_s": 300},
        "current": None if me is None else {
            "source": me.source,
            "zone_en": me.zone_en, "zone_mr": me.zone_mr, "zone_hi": me.zone_hi,
            "inside_geofence": me.inside_geofence,
            "server_ts": me.server_ts.isoformat(),
        },
    }


@router.post("/ping")
async def ingest_pings(
    body: PresencePingBatchIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Batched, idempotent, rate-limited ingest. Server re-checks every gate —
    the client is never trusted about being on shift."""
    fs = await _settings(session)
    if not fs.live_presence_enabled:
        raise HTTPException(status_code=403, detail="presence_disabled")
    if employee.emp_id not in _pilot_set(fs):
        raise HTTPException(status_code=403, detail="not_in_pilot")
    if not await _has_consent(session, employee.id):
        raise HTTPException(status_code=403, detail="consent_required")
    if not await _punched_in(session, employee.id):
        raise HTTPException(status_code=409, detail="not_punched_in")

    rl_key = f"presence:rl:{employee.emp_id}"
    if not await redis_client.set(rl_key, "1", ex=PING_MIN_GAP_S, nx=True):
        raise HTTPException(status_code=429, detail="Too many pings — min 20s between batches")

    zones = await _zone_lookup(session)
    me = (
        await session.execute(select(WorkerPresence).where(WorkerPresence.employee_id == employee.id))
    ).scalar_one_or_none()

    now = now_ist()
    accepted = 0
    skipped_dup = 0
    for ping in body.pings:
        fresh = await redis_client.set(
            f"presence:dedupe:{employee.id}:{ping.client_ping_id}", "1", ex=7200, nx=True
        )
        if not fresh:
            skipped_dup += 1
            continue

        # honest timestamps: an offline-queued ping keeps its own (old) time
        eff_ts = now
        if ping.client_ts is not None:
            cts = ping.client_ts if ping.client_ts.tzinfo else ping.client_ts.replace(tzinfo=now.tzinfo)
            cts = min(cts, now)  # clamp future client clocks
            if (now - cts).total_seconds() > OFFLINE_CATCHUP_S:
                eff_ts = cts

        source = ping.source
        beacon = zones.get(ping.zone_key.lower()) if (source == "beacon" and ping.zone_key) else None
        if source == "beacon" and beacon is None:
            # unknown beacon key — fall back to GPS if coordinates came along
            source = "gps" if ping.lat is not None and ping.lng is not None else None
            if source is None:
                continue

        inside = None
        if source == "gps" and ping.lat is not None and ping.lng is not None:
            inside = _haversine_m(ping.lat, ping.lng, fs.factory_lat, fs.factory_lng) <= fs.radius_meters

        zone_key = None
        if beacon is not None:
            zone_key = (
                f"{beacon.beacon_uuid.lower()}:{beacon.major}:{beacon.minor}"
                if beacon.beacon_uuid is not None else f"mac:{(beacon.mac_address or '').lower()}"
            )

        session.add(PresenceHistory(
            id=uuid_mod.uuid4(), employee_id=employee.id, source=source,
            zone_key=zone_key, zone_en=beacon.zone_label_en if beacon else None,
            lat=ping.lat, lng=ping.lng, accuracy_m=ping.accuracy_m,
            inside_geofence=inside, battery_pct=ping.battery_pct,
            client_ts=ping.client_ts, server_ts=eff_ts, is_demo=employee.is_demo,
        ))

        if me is None:
            me = WorkerPresence(employee_id=employee.id, source=source, server_ts=eff_ts)
            session.add(me)
        elif eff_ts < me.server_ts:
            accepted += 1
            continue  # history recorded, but never move the LIVE state backwards
        me.source = source
        me.zone_since = eff_ts if zone_key != me.zone_key else me.zone_since
        me.zone_key = zone_key
        me.zone_en = beacon.zone_label_en if beacon else None
        me.zone_hi = beacon.zone_label_hi if beacon else None
        me.zone_mr = beacon.zone_label_mr if beacon else None
        me.lat, me.lng, me.accuracy_m = ping.lat, ping.lng, ping.accuracy_m
        me.inside_geofence = inside
        me.battery_pct = ping.battery_pct if ping.battery_pct is not None else me.battery_pct
        me.app_version = ping.app_version or me.app_version
        me.client_ts = ping.client_ts
        me.server_ts = eff_ts
        me.is_demo = employee.is_demo
        accepted += 1

    await session.commit()
    return {"accepted": accepted, "duplicates": skipped_dup, "heartbeat_s": 300}


# ---------------------------------------------------------------- dashboard

async def _require_presence_viewer(session: AsyncSession, actor: Employee) -> str | None:
    """Returns the department scope: None = see everything, else a dept code.
    CGM/MD + Time Office & Security managers see all; other dept managers see
    ONLY their own department; everyone else is refused."""
    role = actor.role
    if role and role.rank <= 2:
        return None
    if actor.role_code == "Manager" and actor.department_code in ("TIME_OFFICE", "SECURITY"):
        return None
    if actor.role_code == "Manager" and actor.department_code:
        return actor.department_code
    raise HTTPException(status_code=403, detail="CGM / MD / Time Office / Security / dept managers only")


def _freshness(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds <= LIVE_S:
        return "live"
    if seconds <= RECENT_S:
        return "recent"
    return "stale"


async def _worker_states(
    session: AsyncSession,
    fs: FactorySettings,
    actor_is_demo: bool,
    dept_filter: str | None,
    now: datetime,
) -> tuple[list[dict], dict, dict]:
    """Shared per-worker status snapshot — the core of /live and /muster."""
    q = (
        select(Attendance, Employee)
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(
            Attendance.date == now.date(),
            Attendance.punch_out_at.is_(None),
            Employee.is_active.is_(True),
            Employee.is_demo.is_(actor_is_demo),
        )
    )
    if dept_filter:
        q = q.where(Employee.department_code == dept_filter)
    rows = (await session.execute(q)).all()

    ids = [e.id for _, e in rows]
    presence = {
        p.employee_id: p
        for p in (
            await session.execute(select(WorkerPresence).where(WorkerPresence.employee_id.in_(ids)))
        ).scalars()
    } if ids else {}
    consented_ids = {
        c
        for c in (
            await session.execute(
                select(PresenceConsent.employee_id).where(
                    PresenceConsent.employee_id.in_(ids),
                    PresenceConsent.version == CONSENT_VERSION,
                )
            )
        ).scalars()
    } if ids else set()
    pilot = _pilot_set(fs)

    workers = []
    counts = {"on_shift": 0, "tracking": 0, "in_zone": 0, "gps_inside": 0,
              "gps_outside": 0, "no_signal": 0, "stopped": 0, "not_tracked": 0}
    zone_counts: dict[str, int] = {}
    for att, emp in rows:
        counts["on_shift"] += 1
        p = presence.get(emp.id)
        tracked = emp.emp_id in pilot and emp.id in consented_ids
        seconds = (now - p.server_ts).total_seconds() if p else None
        fresh = _freshness(seconds)
        if not tracked:
            status = "not_tracked"
        elif p is None:
            status = "no_signal"
        elif p.source == "stopped":
            status = "stopped"
        elif fresh == "stale":
            status = "no_signal"
        elif p.source == "beacon":
            status = "in_zone"
        else:
            status = "gps_inside" if p.inside_geofence else "gps_outside"
        if tracked:
            counts["tracking"] += 1
        counts[status] += 1
        if status == "in_zone" and p and p.zone_key:
            zone_counts[p.zone_key] = zone_counts.get(p.zone_key, 0) + 1
        workers.append({
            "id": str(emp.id), "emp_id": emp.emp_id, "full_name": emp.full_name,
            "department_code": emp.department_code, "status": status,
            "freshness": fresh, "seconds_since": int(seconds) if seconds is not None else None,
            "zone_key": p.zone_key if p else None,
            "zone_en": p.zone_en if p else None, "zone_hi": p.zone_hi if p else None,
            "zone_mr": p.zone_mr if p else None,
            "zone_since": p.zone_since.isoformat() if p and p.zone_since else None,
            "lat": p.lat if p else None, "lng": p.lng if p else None,
            "accuracy_m": p.accuracy_m if p else None,
            "inside_geofence": p.inside_geofence if p else None,
            "battery_pct": p.battery_pct if p else None,
            "app_version": p.app_version if p else None,
            "last_seen": p.server_ts.isoformat() if p else None,
            "punched_in_at": att.punch_in_at.isoformat(),
        })
    return workers, counts, zone_counts


@router.get("/live")
async def live_snapshot(
    dept: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    scope = await _require_presence_viewer(session, actor)
    fs = await _settings(session)
    if not fs.live_presence_enabled:
        return {"enabled": False, "generated_at": now_ist().isoformat()}

    # audit each viewer at most once per 5 min (no audit floods)
    if await redis_client.set(f"presence:view:{actor.id}", "1", ex=300, nx=True):
        await write_audit(
            session, actor.id, "presence.dashboard_view", "settings", None,
            {"scope": scope or "all"}, is_demo=actor.is_demo,
        )
        await session.commit()

    now = now_ist()
    workers, counts, zone_counts = await _worker_states(
        session, fs, actor.is_demo, scope or dept, now
    )

    zones = []
    seen_keys = set()
    for b in (await session.execute(select(BleBeacon).where(BleBeacon.is_active.is_(True)))).scalars():
        key = (
            f"{b.beacon_uuid.lower()}:{b.major}:{b.minor}"
            if b.beacon_uuid is not None and b.major is not None and b.minor is not None
            else f"mac:{(b.mac_address or '').lower()}"
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        zones.append({
            "key": key, "name_en": b.zone_label_en, "name_hi": b.zone_label_hi,
            "name_mr": b.zone_label_mr, "count": zone_counts.get(key, 0),
        })
    zones.sort(key=lambda z: (-z["count"], z["name_en"]))

    return {
        "enabled": True,
        "generated_at": now.isoformat(),
        "scope": scope or "all",
        "geofence": {"lat": fs.factory_lat, "lng": fs.factory_lng, "radius_m": fs.radius_meters},
        "thresholds": {"live_s": LIVE_S, "recent_s": RECENT_S},
        "counts": counts,
        "zones": zones,
        "workers": workers,
    }


# ------------------------------------------------- Phase 2 (v1.0.26): alerts

@router.get("/alerts")
async def list_alerts(
    status: str = "open",
    dept: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """open (active+acknowledged, default) | resolved (last 7 days) | all."""
    scope = await _require_presence_viewer(session, actor)
    dept_filter = scope or dept
    now = now_ist()
    q = (
        select(PresenceAlert, Employee)
        .join(Employee, Employee.id == PresenceAlert.employee_id)
        .where(PresenceAlert.is_demo.is_(actor.is_demo))
    )
    if dept_filter:
        q = q.where(Employee.department_code == dept_filter)
    if status == "open":
        q = q.where(PresenceAlert.status.in_(OPEN_STATUSES))
    elif status == "resolved":
        q = q.where(
            PresenceAlert.status == "resolved",
            PresenceAlert.last_seen_at >= now - timedelta(days=7),
        )
    elif status != "all":
        raise HTTPException(status_code=400, detail="status must be open|resolved|all")
    rows = (await session.execute(q.order_by(PresenceAlert.last_seen_at.desc()).limit(200))).all()

    cq = (
        select(PresenceAlert.alert_type, func.count())
        .select_from(PresenceAlert)
        .join(Employee, Employee.id == PresenceAlert.employee_id)
        .where(PresenceAlert.is_demo.is_(actor.is_demo), PresenceAlert.status.in_(OPEN_STATUSES))
        .group_by(PresenceAlert.alert_type)
    )
    if dept_filter:
        cq = cq.where(Employee.department_code == dept_filter)
    by_type = {t: n for t, n in (await session.execute(cq)).all()}

    return {
        "generated_at": now.isoformat(),
        "scope": scope or "all",
        "open_total": sum(by_type.values()),
        "open_by_type": by_type,
        "alerts": [
            {
                "id": str(a.id), "employee_id": str(e.id), "emp_id": e.emp_id,
                "full_name": e.full_name, "department_code": e.department_code,
                "alert_type": a.alert_type, "status": a.status,
                "zone_key": a.zone_key, "zone_en": a.zone_en, "detail": a.detail,
                "first_seen_at": a.first_seen_at.isoformat(),
                "last_seen_at": a.last_seen_at.isoformat(),
                "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                "auto_resolved": a.status == "resolved" and a.resolved_by is None,
            }
            for a, e in rows
        ],
    }


async def _scoped_alert(session: AsyncSession, actor: Employee, alert_id: str) -> PresenceAlert:
    scope = await _require_presence_viewer(session, actor)
    try:
        aid = uuid_mod.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert = await session.get(PresenceAlert, aid)
    if alert is None or alert.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Alert not found")
    if scope:
        emp = await session.get(Employee, alert.employee_id)
        if emp is None or emp.department_code != scope:
            raise HTTPException(status_code=403, detail="Outside your department scope")
    return alert


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: str,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    alert = await _scoped_alert(session, actor, alert_id)
    if alert.status == "resolved":
        raise HTTPException(status_code=409, detail="Alert already resolved")
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_by = actor.id
        alert.acknowledged_at = now_ist()
        await write_audit(
            session, actor.id, "presence.alert_acknowledged", "presence_alert", str(alert.id),
            {"type": alert.alert_type}, is_demo=actor.is_demo,
        )
        await session.commit()
    return {"status": alert.status}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    alert = await _scoped_alert(session, actor, alert_id)
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_by = actor.id
        alert.resolved_at = now_ist()
        await write_audit(
            session, actor.id, "presence.alert_resolved", "presence_alert", str(alert.id),
            {"type": alert.alert_type}, is_demo=actor.is_demo,
        )
        await session.commit()
    return {"status": "resolved"}


# ------------------------------------------------- Phase 2: muster (roll-call)

@router.get("/muster")
async def muster_snapshot(
    dept: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """One-shot roll-call snapshot: inside / outside / unknown RIGHT NOW.
    'unknown' is honest — no signal, stopped or not tracked, never guessed."""
    scope = await _require_presence_viewer(session, actor)
    fs = await _settings(session)
    if not fs.live_presence_enabled:
        return {"enabled": False, "generated_at": now_ist().isoformat()}
    now = now_ist()
    workers, counts, _ = await _worker_states(session, fs, actor.is_demo, scope or dept, now)
    groups: dict[str, list] = {"inside": [], "outside": [], "unknown": []}
    for w in workers:
        g = ("inside" if w["status"] in ("in_zone", "gps_inside")
             else "outside" if w["status"] == "gps_outside" else "unknown")
        groups[g].append(w)
    for g in groups.values():
        g.sort(key=lambda w: w["full_name"])
    # audit each muster-taker at most once per minute (retakes don't flood)
    if await redis_client.set(f"presence:muster:{actor.id}", "1", ex=60, nx=True):
        await write_audit(
            session, actor.id, "presence.muster_taken", "settings", None,
            {"inside": len(groups["inside"]), "outside": len(groups["outside"]),
             "unknown": len(groups["unknown"])}, is_demo=actor.is_demo,
        )
        await session.commit()
    return {
        "enabled": True, "generated_at": now.isoformat(), "scope": scope or "all",
        "counts": {"on_shift": counts["on_shift"], "inside": len(groups["inside"]),
                   "outside": len(groups["outside"]), "unknown": len(groups["unknown"])},
        "groups": groups,
    }


# ------------------------------------------------- Phase 2: shift summary

def _bucket(row: PresenceHistory) -> tuple[str, str | None]:
    """(kind, zone_key) a history row's time counts toward."""
    if row.source == "stopped":
        return "stopped", None
    if row.source == "beacon" and row.zone_key:
        return "zone", row.zone_key
    if row.source == "gps":
        return ("gps_outside", None) if row.inside_geofence is False else ("gps_inside", None)
    return "skip", None


def _day_bounds(day: date_cls, now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time_cls.min, tzinfo=now.tzinfo)
    return start, start + timedelta(days=1)


@router.get("/shift-summary")
async def shift_summary(
    date: str | None = None,
    dept: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """Per-worker time-in-zone for one day. Each ping covers until the next one
    (capped at 10 min) so a dead phone never silently inflates zone hours."""
    scope = await _require_presence_viewer(session, actor)
    fs = await _settings(session)
    if not fs.live_presence_enabled:
        return {"enabled": False, "generated_at": now_ist().isoformat()}
    now = now_ist()
    try:
        day = date_cls.fromisoformat(date) if date else now.date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if day > now.date():
        raise HTTPException(status_code=400, detail="date cannot be in the future")
    day_start, day_end = _day_bounds(day, now)
    dept_filter = scope or dept

    q = (
        select(Attendance, Employee)
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(
            Attendance.date == day,
            Employee.is_active.is_(True),
            Employee.is_demo.is_(actor.is_demo),
        )
    )
    if dept_filter:
        q = q.where(Employee.department_code == dept_filter)
    rows = (await session.execute(q)).all()
    ids = [e.id for _, e in rows]

    hist_by_emp: dict = {}
    if ids:
        hq = (
            select(PresenceHistory)
            .where(
                PresenceHistory.employee_id.in_(ids),
                PresenceHistory.server_ts >= day_start,
                PresenceHistory.server_ts < day_end,
            )
            .order_by(PresenceHistory.server_ts)
        )
        for h in (await session.execute(hq)).scalars():
            hist_by_emp.setdefault(h.employee_id, []).append(h)

    zones_reg = await _zone_lookup(session)
    pilot = _pilot_set(fs)
    consented_ids = {
        c
        for c in (
            await session.execute(
                select(PresenceConsent.employee_id).where(
                    PresenceConsent.employee_id.in_(ids),
                    PresenceConsent.version == CONSENT_VERSION,
                )
            )
        ).scalars()
    } if ids else set()

    workers = []
    for att, emp in rows:
        hrows = hist_by_emp.get(emp.id, [])
        if att.punch_out_at is not None:
            end_anchor = att.punch_out_at
        elif day == now.date():
            end_anchor = now
        else:
            end_anchor = None  # past day, never punched out — duration unknowable
        tail_anchor = end_anchor or day_end

        buckets: dict[tuple, float] = {}
        for i, h in enumerate(hrows):
            kind, zkey = _bucket(h)
            if kind in ("stopped", "skip"):
                continue
            if i + 1 < len(hrows):
                seg_end = hrows[i + 1].server_ts
            else:
                seg_end = h.server_ts + timedelta(seconds=GAP_CAP_S)
            # clip to the shift window — pre-punch-in trail never inflates coverage
            start = max(h.server_ts, att.punch_in_at)
            end = min(seg_end, tail_anchor)
            dur = max(0.0, min((end - start).total_seconds(), GAP_CAP_S))
            buckets[(kind, zkey)] = buckets.get((kind, zkey), 0.0) + dur

        zone_list = []
        gps_inside_s = gps_outside_s = 0.0
        for (kind, zkey), secs in buckets.items():
            if kind == "zone":
                b = zones_reg.get(zkey)
                zone_list.append({
                    "zone_key": zkey,
                    "zone_en": b.zone_label_en if b else zkey,
                    "zone_hi": b.zone_label_hi if b else None,
                    "zone_mr": b.zone_label_mr if b else None,
                    "minutes": int(secs // 60),
                })
            elif kind == "gps_inside":
                gps_inside_s = secs
            else:
                gps_outside_s = secs
        zone_list.sort(key=lambda z: -z["minutes"])

        tracked_s = sum(buckets.values())
        shift_s = (end_anchor - att.punch_in_at).total_seconds() if end_anchor else None
        coverage = (
            min(100, int(round(100 * tracked_s / shift_s)))
            if shift_s and shift_s > 0 else None
        )
        workers.append({
            "id": str(emp.id), "emp_id": emp.emp_id, "full_name": emp.full_name,
            "department_code": emp.department_code,
            "tracked": emp.emp_id in pilot and emp.id in consented_ids,
            "punch_in_at": att.punch_in_at.isoformat(),
            "punch_out_at": att.punch_out_at.isoformat() if att.punch_out_at else None,
            "shift_min": int(shift_s // 60) if shift_s is not None else None,
            "tracked_min": int(tracked_s // 60),
            "coverage_pct": coverage,
            "zones": zone_list,
            "gps_inside_min": int(gps_inside_s // 60),
            "outside_min": int(gps_outside_s // 60),
        })
    workers.sort(key=lambda w: (not w["tracked"], w["full_name"]))

    covs = [w["coverage_pct"] for w in workers if w["tracked"] and w["coverage_pct"] is not None]
    return {
        "enabled": True, "generated_at": now.isoformat(), "date": day.isoformat(),
        "scope": scope or "all",
        "counts": {
            "workers": len(workers),
            "tracked": sum(1 for w in workers if w["tracked"]),
            "avg_coverage_pct": int(round(sum(covs) / len(covs))) if covs else 0,
        },
        "workers": workers,
    }


# ------------------------------------------------- Phase 2: timeline + trail

@router.get("/timeline")
async def worker_timeline(
    employee_id: str,
    date: str | None = None,
    actor: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    """One worker's day: raw trail points + merged zone entry/exit segments.
    Gaps longer than 10 min surface as honest 'no_data' segments."""
    scope = await _require_presence_viewer(session, actor)
    try:
        eid = uuid_mod.UUID(employee_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Worker not found")
    emp = await session.get(Employee, eid)
    if emp is None or emp.is_demo != actor.is_demo:
        raise HTTPException(status_code=404, detail="Worker not found")
    if scope and emp.department_code != scope:
        raise HTTPException(status_code=403, detail="Outside your department scope")
    fs = await _settings(session)
    now = now_ist()
    try:
        day = date_cls.fromisoformat(date) if date else now.date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    day_start, day_end = _day_bounds(day, now)

    # individual-trail privacy: audit each viewer/worker pair (5-min throttle)
    if await redis_client.set(f"presence:tl:{actor.id}:{eid}", "1", ex=300, nx=True):
        await write_audit(
            session, actor.id, "presence.timeline_view", "employee", str(eid),
            {"date": day.isoformat()}, is_demo=actor.is_demo,
        )
        await session.commit()

    att = (
        await session.execute(
            select(Attendance).where(
                Attendance.employee_id == eid, Attendance.date == day
            ).limit(1)
        )
    ).scalars().first()
    hrows = list((
        await session.execute(
            select(PresenceHistory).where(
                PresenceHistory.employee_id == eid,
                PresenceHistory.server_ts >= day_start,
                PresenceHistory.server_ts < day_end,
            ).order_by(PresenceHistory.server_ts)
        )
    ).scalars())

    zones_reg = await _zone_lookup(session)

    def _zlabel(zkey: str | None) -> dict:
        b = zones_reg.get(zkey) if zkey else None
        return {
            "zone_en": b.zone_label_en if b else None,
            "zone_hi": b.zone_label_hi if b else None,
            "zone_mr": b.zone_label_mr if b else None,
        }

    points = [{
        "ts": h.server_ts.isoformat(), "source": h.source, "zone_key": h.zone_key,
        "zone_en": h.zone_en, "lat": h.lat, "lng": h.lng, "accuracy_m": h.accuracy_m,
        "inside_geofence": h.inside_geofence, "battery_pct": h.battery_pct,
    } for h in hrows]

    if att and att.punch_out_at:
        end_anchor = att.punch_out_at
    elif day == now.date():
        end_anchor = now
    else:
        end_anchor = day_end

    segments: list[dict] = []
    cur: dict | None = None
    prev_ts: datetime | None = None
    for h in hrows:
        kind, zkey = _bucket(h)
        if kind == "skip":
            continue
        if cur is not None and prev_ts is not None:
            gap = (h.server_ts - prev_ts).total_seconds()
            if gap > GAP_CAP_S:
                cur["to"] = prev_ts + timedelta(seconds=GAP_CAP_S)
                segments.append(cur)
                segments.append({"kind": "no_data", "zone_key": None,
                                 "from": cur["to"], "to": h.server_ts})
                cur = None
            elif (kind, zkey) != (cur["kind"], cur["zone_key"]):
                cur["to"] = h.server_ts
                segments.append(cur)
                cur = None
        if cur is None:
            cur = {"kind": kind, "zone_key": zkey, "from": h.server_ts, "to": h.server_ts}
        prev_ts = h.server_ts
    if cur is not None and prev_ts is not None:
        tail = prev_ts + timedelta(seconds=GAP_CAP_S)
        if end_anchor > prev_ts:
            tail = min(tail, end_anchor)
        cur["to"] = tail
        segments.append(cur)

    seg_out = [{
        "kind": s["kind"], "zone_key": s["zone_key"], **_zlabel(s["zone_key"]),
        "from_ts": s["from"].isoformat(), "to_ts": s["to"].isoformat(),
        "minutes": max(0, int((s["to"] - s["from"]).total_seconds() // 60)),
    } for s in segments]

    zone_list = []
    seen_ids = set()
    for key, b in zones_reg.items():
        if b.id in seen_ids:
            continue
        seen_ids.add(b.id)
        zone_list.append({"key": key, "name_en": b.zone_label_en,
                          "name_hi": b.zone_label_hi, "name_mr": b.zone_label_mr})

    return {
        "generated_at": now.isoformat(), "date": day.isoformat(),
        "worker": {"id": str(emp.id), "emp_id": emp.emp_id, "full_name": emp.full_name,
                   "department_code": emp.department_code},
        "punch_in_at": att.punch_in_at.isoformat() if att else None,
        "punch_out_at": att.punch_out_at.isoformat() if att and att.punch_out_at else None,
        "geofence": {"lat": fs.factory_lat, "lng": fs.factory_lng, "radius_m": fs.radius_meters},
        "points": points,
        "segments": seg_out,
        "zones": zone_list,
    }


# ---------------------------------------------------------------- admin

@router.get("/settings")
async def get_presence_settings(
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    fs = await _settings(session)
    return {
        "live_presence_enabled": fs.live_presence_enabled,
        "presence_pilot_emp_ids": fs.presence_pilot_emp_ids,
        "presence_nosignal_alert_min": fs.presence_nosignal_alert_min,
        "presence_outside_alert_min": fs.presence_outside_alert_min,
        "consent_version": CONSENT_VERSION,
    }


@router.put("/settings")
async def update_presence_settings(
    body: PresenceSettingsIn,
    actor: Employee = Depends(require_real_role(2)),
    session: AsyncSession = Depends(get_session),
):
    fs = await _settings(session)
    changed = {}
    for field in ("live_presence_enabled", "presence_pilot_emp_ids",
                  "presence_nosignal_alert_min", "presence_outside_alert_min"):
        val = getattr(body, field)
        if val is not None and getattr(fs, field) != val:
            setattr(fs, field, val)
            changed[field] = val
    if changed:
        await write_audit(
            session, actor.id, "presence.settings_changed", "settings", None, changed, is_demo=False,
        )
        await session.commit()
    return await get_presence_settings(actor, session)  # type: ignore[arg-type]


# ---------------------------------------------------------------- demo bubble

@router.post("/demo-simulate")
async def demo_simulate(
    actor: Employee = Depends(require_role(2)),
    session: AsyncSession = Depends(get_session),
):
    """Scripted demo-day: puts the demo cast (is_demo=True) into zones / GPS
    inside / GPS outside / stale / stopped / not-tracked states so the whole
    dashboard is demo-able with zero real phones. Touches ONLY demo rows
    (plus the global flag + pilot list, which is additive and audited)."""
    fs = await _settings(session)
    demo_workers = (
        await session.execute(
            select(Employee).where(
                Employee.is_demo.is_(True), Employee.is_active.is_(True),
                Employee.role_code.in_(["Worker", "Staff", "Clerk"]),
            ).order_by(Employee.emp_id).limit(16)
        )
    ).scalars().all()
    if not demo_workers:
        raise HTTPException(status_code=404, detail="No demo workers seeded")

    beacons = (
        await session.execute(select(BleBeacon).where(BleBeacon.is_active.is_(True)).limit(8))
    ).scalars().all()

    now = now_ist()
    # not-tracked demo cast: the last two stay OUT of the pilot list
    tracked, untracked = demo_workers[:-2], demo_workers[-2:]

    # Phase 2 (idempotent re-runs): wipe today's demo trail before re-seeding
    day_start = datetime.combine(now.date(), time_cls.min, tzinfo=now.tzinfo)
    await session.execute(delete(PresenceHistory).where(
        PresenceHistory.employee_id.in_([w.id for w in demo_workers]),
        PresenceHistory.is_demo.is_(True),
        PresenceHistory.server_ts >= day_start,
    ))

    if not fs.live_presence_enabled:
        fs.live_presence_enabled = True
    pilot = _pilot_set(fs)
    pilot.update(w.emp_id for w in tracked)
    fs.presence_pilot_emp_ids = ",".join(sorted(pilot))

    for w in demo_workers:
        att = (
            await session.execute(
                select(Attendance).where(Attendance.employee_id == w.id, Attendance.date == now.date())
            )
        ).scalar_one_or_none()
        if att is None:
            session.add(Attendance(
                employee_id=w.id, date=now.date(), punch_in_at=now - timedelta(hours=2),
                selfie_key="demo-sim.jpg", verification_level="verified",
                shift_code="GEN", is_demo=True,
            ))
        elif att.punch_out_at is not None:
            att.punch_out_at = None

    for w in tracked:
        if not await _has_consent(session, w.id):
            session.add(PresenceConsent(
                employee_id=w.id, version=CONSENT_VERSION, lang="mr", granted_at=now,
            ))

    async def _put(w: Employee, **kw):
        me = (
            await session.execute(select(WorkerPresence).where(WorkerPresence.employee_id == w.id))
        ).scalar_one_or_none()
        if me is None:
            me = WorkerPresence(employee_id=w.id, source=kw["source"], server_ts=kw["server_ts"])
            session.add(me)
        for k, v in kw.items():
            setattr(me, k, v)
        me.is_demo = True
        session.add(PresenceHistory(
            id=uuid_mod.uuid4(), employee_id=w.id, source=kw["source"],
            zone_key=kw.get("zone_key"), zone_en=kw.get("zone_en"),
            lat=kw.get("lat"), lng=kw.get("lng"), accuracy_m=kw.get("accuracy_m"),
            inside_geofence=kw.get("inside_geofence"), battery_pct=kw.get("battery_pct"),
            client_ts=kw["server_ts"], server_ts=kw["server_ts"], is_demo=True,
        ))

    def _zkey(b: BleBeacon) -> str:
        return (
            f"{b.beacon_uuid.lower()}:{b.major}:{b.minor}"
            if b.beacon_uuid is not None else f"mac:{(b.mac_address or '').lower()}"
        )

    i = 0
    for w in tracked:
        if i < max(1, len(tracked) - 5) and beacons:  # most of the cast in zones
            b = beacons[i % len(beacons)]
            await _put(w, source="beacon", zone_key=_zkey(b), zone_en=b.zone_label_en,
                       zone_hi=b.zone_label_hi, zone_mr=b.zone_label_mr,
                       zone_since=now - timedelta(minutes=25 + i * 3), lat=None, lng=None,
                       accuracy_m=None, inside_geofence=None, battery_pct=88 - i * 4,
                       app_version="1.0.24", client_ts=now, server_ts=now)
        elif i == len(tracked) - 5:  # GPS inside the geofence
            await _put(w, source="gps", zone_key=None, zone_en=None, zone_hi=None, zone_mr=None,
                       zone_since=None, lat=fs.factory_lat + 0.004, lng=fs.factory_lng - 0.003,
                       accuracy_m=18.0, inside_geofence=True, battery_pct=64,
                       app_version="1.0.24", client_ts=now, server_ts=now)
        elif i == len(tracked) - 4:  # GPS inside, second dot
            await _put(w, source="gps", zone_key=None, zone_en=None, zone_hi=None, zone_mr=None,
                       zone_since=None, lat=fs.factory_lat - 0.005, lng=fs.factory_lng + 0.002,
                       accuracy_m=25.0, inside_geofence=True, battery_pct=47,
                       app_version="1.0.24", client_ts=now, server_ts=now)
        elif i == len(tracked) - 3:  # OUTSIDE the geofence
            await _put(w, source="gps", zone_key=None, zone_en=None, zone_hi=None, zone_mr=None,
                       zone_since=None, lat=fs.factory_lat + 0.016, lng=fs.factory_lng + 0.013,
                       accuracy_m=22.0, inside_geofence=False, battery_pct=71,
                       app_version="1.0.24", client_ts=now, server_ts=now)
        elif i == len(tracked) - 2:  # stale — last seen 22 min ago
            b = beacons[0] if beacons else None
            await _put(w, source="beacon" if b else "gps",
                       zone_key=_zkey(b) if b else None, zone_en=b.zone_label_en if b else None,
                       zone_hi=b.zone_label_hi if b else None, zone_mr=b.zone_label_mr if b else None,
                       zone_since=now - timedelta(minutes=50), lat=None, lng=None, accuracy_m=None,
                       inside_geofence=None, battery_pct=9, app_version="1.0.24",
                       client_ts=now - timedelta(minutes=22), server_ts=now - timedelta(minutes=22))
        else:  # explicitly stopped tracking
            await _put(w, source="stopped", zone_key=None, zone_en=None, zone_hi=None, zone_mr=None,
                       zone_since=None, lat=None, lng=None, accuracy_m=None, inside_geofence=None,
                       battery_pct=55, app_version="1.0.24", client_ts=now, server_ts=now)
        i += 1

    # Phase 2 demo: a 2-hour replayable trail (zone hops + one GPS wander) for
    # the zone cast so Shift Summary / Timeline / Trail replay are demo-able.
    zone_cast = tracked[: max(1, len(tracked) - 5)]
    for j, w in enumerate(zone_cast):
        if not beacons:
            break
        t0 = now - timedelta(hours=2)
        for k in range(12):
            ts = t0 + timedelta(minutes=10 * k)
            if ts >= now:
                break
            if k == 6:  # mid-shift GPS wander inside the geofence
                session.add(PresenceHistory(
                    id=uuid_mod.uuid4(), employee_id=w.id, source="gps",
                    lat=fs.factory_lat + 0.002 + j * 0.0004, lng=fs.factory_lng + 0.002,
                    accuracy_m=20.0, inside_geofence=True, battery_pct=90 - k * 3,
                    client_ts=ts, server_ts=ts, is_demo=True,
                ))
                continue
            b = beacons[(j + k // 4) % len(beacons)]
            session.add(PresenceHistory(
                id=uuid_mod.uuid4(), employee_id=w.id, source="beacon",
                zone_key=_zkey(b), zone_en=b.zone_label_en, battery_pct=90 - k * 3,
                client_ts=ts, server_ts=ts, is_demo=True,
            ))

    await write_audit(
        session, actor.id, "presence.demo_simulated", "settings", None,
        {"tracked": len(tracked), "untracked": len(untracked)}, is_demo=True,
    )
    await session.commit()
    return {
        "status": "simulated",
        "tracked": len(tracked),
        "not_tracked": [w.emp_id for w in untracked],
        "note": "live_presence_enabled turned ON; demo emp_ids added to pilot list",
    }
