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
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.database import get_session
from app.models import (
    Attendance,
    BleBeacon,
    Employee,
    FactorySettings,
    PresenceConsent,
    PresenceHistory,
    WorkerPresence,
)
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

    dept_filter = scope or dept
    q = (
        select(Attendance, Employee)
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(
            Attendance.date == now_ist().date(),
            Attendance.punch_out_at.is_(None),
            Employee.is_active.is_(True),
            Employee.is_demo.is_(actor.is_demo),
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

    now = now_ist()
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
