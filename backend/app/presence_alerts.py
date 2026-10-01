"""v1.0.26 LIVE PRESENCE Phase 2 — alerts engine.

Minute sweep (Celery beat + in-process APScheduler, Redis job-locked) that
raises, refreshes and auto-resolves alerts for every TRACKED on-shift worker:

  outside_geofence   fresh GPS fix outside the factory circle for >=
                     settings.presence_outside_alert_min (persistence timer
                     kept in Redis so a single stray fix never alerts)
  gone_dark          punched in but silent for >= presence_nosignal_alert_min
                     (an explicit worker "stopped" is NOT gone-dark — honesty)
  low_battery        fresh ping with battery < 15% (clears at >= 20%)
  unauthorized_zone  fresh beacon fix in a zone owned by ANOTHER department

Dedupe: ONE open row per (employee, alert_type) — re-detections only bump
last_seen_at/detail. Notifications go to the worker's department manager(s)
plus Time Office & Security managers ON RAISE ONLY, never on refresh.
Auto-resolve: condition cleared OR worker punched out / left the pilot.
"""
import logging
import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    BleBeacon,
    Employee,
    FactorySettings,
    PresenceAlert,
    PresenceConsent,
    WorkerPresence,
)
from app.notify import dispatcher, template
from app.redis_client import redis_client
from app.shift_logic import now_ist

logger = logging.getLogger("hogo.presence_alerts")

RECENT_S = 15 * 60  # same freshness ceiling as the live dashboard
LOW_BATTERY_PCT = 15
LOW_BATTERY_CLEAR_PCT = 20  # hysteresis so 14→16→14 doesn't flap
OPEN_STATUSES = ("active", "acknowledged")
ALERT_TYPES = ("outside_geofence", "gone_dark", "low_battery", "unauthorized_zone")

# alert_type → notification template key in app.notify.T
NOTIF_TYPE = {
    "outside_geofence": "presence_outside",
    "gone_dark": "presence_gone_dark",
    "low_battery": "presence_low_battery",
    "unauthorized_zone": "presence_unauthorized_zone",
}


def _body(alert_type: str, emp: Employee, ctx: dict) -> dict:
    who = f"{emp.full_name} (#{emp.emp_id})"
    if alert_type == "outside_geofence":
        m = ctx.get("minutes", 0)
        return {
            "en": f"{who} has been outside the factory boundary for {m} min.",
            "hi": f"{who} {m} मिनट से फ़ैक्टरी सीमा के बाहर है।",
            "mr": f"{who} {m} मिनिटांपासून कारखाना हद्दीबाहेर आहे.",
        }
    if alert_type == "gone_dark":
        m = ctx.get("minutes", 0)
        return {
            "en": f"No signal from {who} for {m} min while on shift.",
            "hi": f"शिफ्ट के दौरान {who} से {m} मिनट से कोई सिग्नल नहीं।",
            "mr": f"शिफ्टदरम्यान {who} कडून {m} मिनिटांपासून सिग्नल नाही.",
        }
    if alert_type == "low_battery":
        b = ctx.get("battery_pct", 0)
        return {
            "en": f"{who}'s phone battery is at {b}% — tracking may stop soon.",
            "hi": f"{who} के फ़ोन की बैटरी {b}% है — ट्रैकिंग रुक सकती है।",
            "mr": f"{who} च्या फोनची बॅटरी {b}% आहे — ट्रॅकिंग थांबू शकते.",
        }
    zone = ctx.get("zone_en") or ctx.get("zone_key") or "?"
    return {
        "en": f"{who} is in '{zone}' — a zone owned by {ctx.get('zone_dept', '?')}.",
        "hi": f"{who} '{zone}' में है — यह {ctx.get('zone_dept', '?')} विभाग का क्षेत्र है।",
        "mr": f"{who} '{zone}' मध्ये आहे — हा {ctx.get('zone_dept', '?')} विभागाचा झोन आहे.",
    }


async def _recipients(session: AsyncSession, emp: Employee, cache: dict) -> list[Employee]:
    """Dept manager(s) of the worker's department + Time Office & Security
    managers, same demo class. Cached per (dept, is_demo) within one sweep."""
    key = (emp.department_code, emp.is_demo)
    if key not in cache:
        q = select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role_code == "Manager",
            Employee.is_demo.is_(emp.is_demo),
            or_(
                Employee.department_code == emp.department_code,
                Employee.department_code.in_(("TIME_OFFICE", "SECURITY")),
            ),
        )
        cache[key] = list((await session.execute(q)).scalars())
    return cache[key]


async def run_presence_alert_sweep(session: AsyncSession, now: datetime | None = None) -> dict:
    """Evaluate all conditions and reconcile presence_alerts. Caller commits."""
    fs = (await session.execute(select(FactorySettings))).scalars().first()
    if fs is None or not fs.live_presence_enabled:
        return {"skipped": "disabled"}
    now = now or now_ist()

    rows = (
        await session.execute(
            select(Attendance, Employee)
            .join(Employee, Employee.id == Attendance.employee_id)
            .where(
                Attendance.date == now.date(),
                Attendance.punch_out_at.is_(None),
                Employee.is_active.is_(True),
            )
        )
    ).all()
    pilot = {s.strip() for s in (fs.presence_pilot_emp_ids or "").split(",") if s.strip()}
    ids = [e.id for _, e in rows]
    presence = {
        p.employee_id: p
        for p in (
            await session.execute(select(WorkerPresence).where(WorkerPresence.employee_id.in_(ids)))
        ).scalars()
    } if ids else {}
    from app.routers.presence import CONSENT_VERSION  # no cycle: router never imports this module

    consented = {
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
    beacon_dept: dict[str, str] = {}
    for b in (await session.execute(select(BleBeacon).where(BleBeacon.is_active.is_(True)))).scalars():
        if not b.department_code:
            continue
        if b.beacon_uuid is not None and b.major is not None and b.minor is not None:
            beacon_dept[f"{b.beacon_uuid.lower()}:{b.major}:{b.minor}"] = b.department_code
        if b.mac_address:
            beacon_dept[f"mac:{b.mac_address.lower()}"] = b.department_code

    open_alerts = {
        (a.employee_id, a.alert_type): a
        for a in (
            await session.execute(select(PresenceAlert).where(PresenceAlert.status.in_(OPEN_STATUSES)))
        ).scalars()
    }

    detected: list[tuple[Employee, str, dict]] = []
    for att, emp in rows:
        if emp.emp_id not in pilot or emp.id not in consented:
            continue
        p = presence.get(emp.id)
        seconds = (now - p.server_ts).total_seconds() if p else None
        fresh = p is not None and p.source != "stopped" and seconds is not None and seconds <= RECENT_S

        # gone_dark — silence since the last ping (or punch-in if never pinged)
        if p is None or p.source != "stopped":
            dark_since = p.server_ts if p else att.punch_in_at
            dark_s = (now - dark_since).total_seconds()
            if dark_s >= fs.presence_nosignal_alert_min * 60:
                detected.append((emp, "gone_dark", {"minutes": int(dark_s // 60)}))

        # outside_geofence — must persist for presence_outside_alert_min
        cond_key = f"presence:cond:out:{emp.id}"
        if fresh and p.source == "gps" and p.inside_geofence is False:
            first = await redis_client.get(cond_key)
            if first is None:
                await redis_client.set(cond_key, now.isoformat(), ex=24 * 3600)
                first_dt = now
            else:
                first_dt = datetime.fromisoformat(first)
            out_s = (now - first_dt).total_seconds()
            if out_s >= fs.presence_outside_alert_min * 60:
                detected.append((emp, "outside_geofence",
                                 {"minutes": int(out_s // 60), "lat": p.lat, "lng": p.lng}))
        else:
            await redis_client.delete(cond_key)

        # low_battery — with clear-hysteresis so an open alert survives 15–19%
        if fresh and p.battery_pct is not None:
            already_open = (emp.id, "low_battery") in open_alerts
            if p.battery_pct < LOW_BATTERY_PCT or (already_open and p.battery_pct < LOW_BATTERY_CLEAR_PCT):
                detected.append((emp, "low_battery", {"battery_pct": p.battery_pct}))

        # unauthorized_zone — beacon zone owned by another department
        if fresh and p.source == "beacon" and p.zone_key:
            zdept = beacon_dept.get(p.zone_key)
            if zdept and emp.department_code and zdept != emp.department_code:
                detected.append((emp, "unauthorized_zone",
                                 {"zone_key": p.zone_key, "zone_en": p.zone_en,
                                  "zone_dept": zdept, "worker_dept": emp.department_code}))

    raised = refreshed = 0
    detected_keys = set()
    recip_cache: dict = {}
    for emp, atype, ctx in detected:
        detected_keys.add((emp.id, atype))
        existing = open_alerts.get((emp.id, atype))
        if existing is not None:
            existing.last_seen_at = now
            existing.detail = ctx
            refreshed += 1
            continue
        alert = PresenceAlert(
            id=uuid_mod.uuid4(), employee_id=emp.id, alert_type=atype, status="active",
            zone_key=ctx.get("zone_key"), zone_en=ctx.get("zone_en"), detail=ctx,
            first_seen_at=now, last_seen_at=now, is_demo=emp.is_demo,
        )
        session.add(alert)
        open_alerts[(emp.id, atype)] = alert
        raised += 1
        title, _ = template(NOTIF_TYPE[atype])
        body = _body(atype, emp, ctx)
        for r in await _recipients(session, emp, recip_cache):
            await dispatcher.notify(
                session, r.id, NOTIF_TYPE[atype], title, body,
                entity_type="presence_alert", entity_id=str(alert.id),
            )

    auto_resolved = 0
    for key, a in open_alerts.items():
        if key not in detected_keys and a.resolved_at is None:
            a.status = "resolved"
            a.resolved_at = now  # resolved_by stays NULL = auto-cleared
            auto_resolved += 1

    return {"raised": raised, "refreshed": refreshed, "auto_resolved": auto_resolved}
