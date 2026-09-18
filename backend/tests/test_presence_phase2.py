"""v1.0.26 LIVE PRESENCE Phase 2 — alerts engine (raise / dedupe / hysteresis /
auto-resolve), ack+resolve endpoints with scoping, muster roll-call grouping,
shift-summary time-in-zone math and the timeline segment builder."""
import uuid as uuid_mod
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import delete, select

from app.models import (
    Attendance,
    AuditEvent,
    Employee,
    FactorySettings,
    Notification,
    PresenceAlert,
    PresenceConsent,
    PresenceHistory,
    WorkerPresence,
)
from app.presence_alerts import run_presence_alert_sweep
from app.routers.presence import CONSENT_VERSION
from app.shift_logic import now_ist
from tests.conftest import PHONES, login

W2_PHONE = "+919666000444"
MILL_GATE_KEY = "mac:aa:bb:cc:dd:ee:01"          # SECURITY-owned zone (conftest)
BOILER_KEY = "f7826da6-4fa2-4e98-8024-bc5b71e0893e:1:1"  # PRODUCTION-owned zone


@pytest_asyncio.fixture
async def env2(client, db_session):
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    worker = Employee(
        emp_id="P902", full_name="Phase2 Worker", phone=W2_PHONE, department_code="PRODUCTION",
        designation="Worker", role_code="Worker", language_pref="mr", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True,
    )
    db_session.add(worker)
    await db_session.flush()
    db_session.add(PresenceConsent(
        employee_id=worker.id, version=CONSENT_VERSION, lang="mr", granted_at=now_ist(),
    ))
    db_session.add(Attendance(
        employee_id=worker.id, date=now_ist().date(), punch_in_at=now_ist() - timedelta(hours=2),
        selfie_key="p2.jpg", verification_level="verified", shift_code="GEN",
    ))
    fs.live_presence_enabled = True
    fs.presence_pilot_emp_ids = "P902"
    fs.presence_outside_alert_min = 2
    fs.presence_nosignal_alert_min = 15
    await db_session.commit()
    yield {"worker": worker}
    # -------- teardown: restore baseline --------
    await db_session.execute(delete(PresenceAlert))
    await db_session.execute(delete(Notification).where(Notification.type.like("presence_%")))
    for model in (WorkerPresence, PresenceHistory, PresenceConsent):
        await db_session.execute(delete(model).where(model.employee_id == worker.id))
    await db_session.execute(delete(Attendance).where(Attendance.employee_id == worker.id))
    await db_session.execute(delete(AuditEvent).where(AuditEvent.action.in_([
        "presence.alert_acknowledged", "presence.alert_resolved",
        "presence.muster_taken", "presence.timeline_view", "presence.dashboard_view",
    ])))
    fs2 = (await db_session.execute(select(FactorySettings))).scalars().first()
    fs2.live_presence_enabled = False
    fs2.presence_pilot_emp_ids = ""
    w = await db_session.get(Employee, worker.id)
    if w:
        await db_session.delete(w)
    await db_session.commit()


async def _set_presence(db_session, employee_id, **kw):
    row = (
        await db_session.execute(select(WorkerPresence).where(WorkerPresence.employee_id == employee_id))
    ).scalar_one_or_none()
    if row is None:
        row = WorkerPresence(employee_id=employee_id, source=kw["source"], server_ts=kw["server_ts"])
        db_session.add(row)
    for k, v in kw.items():
        setattr(row, k, v)
    await db_session.commit()
    return row


async def _open_alerts(db_session, employee_id, alert_type=None):
    q = select(PresenceAlert).where(
        PresenceAlert.employee_id == employee_id,
        PresenceAlert.status.in_(("active", "acknowledged")),
    )
    if alert_type:
        q = q.where(PresenceAlert.alert_type == alert_type)
    return list((await db_session.execute(q)).scalars())


async def test_gone_dark_raises_notifies_and_autoresolves(client, db_session, env2):
    w = env2["worker"]
    # never pinged since punch-in (2 h ago) -> gone dark after 15 min
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    alerts = await _open_alerts(db_session, w.id, "gone_dark")
    assert len(alerts) == 1 and alerts[0].status == "active"
    assert alerts[0].detail["minutes"] >= 115

    # notifications fan out to dept manager + Time Office + Security managers
    notifs = list((await db_session.execute(
        select(Notification).where(Notification.type == "presence_gone_dark")
    )).scalars())
    assert len({n.recipient_id for n in notifs}) >= 3

    # second sweep: refresh, never duplicate — and no second notification burst
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert len(await _open_alerts(db_session, w.id, "gone_dark")) == 1
    notifs2 = list((await db_session.execute(
        select(Notification).where(Notification.type == "presence_gone_dark")
    )).scalars())
    assert len(notifs2) == len(notifs)

    # a fresh ping clears it automatically
    await _set_presence(db_session, w.id, source="beacon", zone_key=BOILER_KEY,
                        zone_en="Boiler House", server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert await _open_alerts(db_session, w.id, "gone_dark") == []
    resolved = (await db_session.execute(select(PresenceAlert).where(
        PresenceAlert.employee_id == w.id, PresenceAlert.alert_type == "gone_dark",
    ))).scalars().first()
    assert resolved.status == "resolved" and resolved.resolved_by is None  # auto


async def test_outside_geofence_needs_persistence(client, db_session, env2):
    w = env2["worker"]
    t0 = now_ist()
    await _set_presence(db_session, w.id, source="gps", inside_geofence=False,
                        lat=19.05, lng=74.75, server_ts=t0)
    # first detection only starts the timer (threshold = 2 min)
    await run_presence_alert_sweep(db_session, now=t0)
    await db_session.commit()
    assert await _open_alerts(db_session, w.id, "outside_geofence") == []
    # still outside 3 min later -> alert
    await run_presence_alert_sweep(db_session, now=t0 + timedelta(minutes=3))
    await db_session.commit()
    alerts = await _open_alerts(db_session, w.id, "outside_geofence")
    assert len(alerts) == 1 and alerts[0].detail["minutes"] >= 3
    # back inside -> auto-resolve
    await _set_presence(db_session, w.id, source="gps", inside_geofence=True,
                        server_ts=t0 + timedelta(minutes=4))
    await run_presence_alert_sweep(db_session, now=t0 + timedelta(minutes=4))
    await db_session.commit()
    assert await _open_alerts(db_session, w.id, "outside_geofence") == []


async def test_low_battery_hysteresis(client, db_session, env2):
    w = env2["worker"]
    await _set_presence(db_session, w.id, source="beacon", zone_key=BOILER_KEY,
                        zone_en="Boiler House", battery_pct=10, server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert len(await _open_alerts(db_session, w.id, "low_battery")) == 1
    # 17% is above the raise threshold but below the clear threshold — stays open
    await _set_presence(db_session, w.id, battery_pct=17, source="beacon", server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert len(await _open_alerts(db_session, w.id, "low_battery")) == 1
    # 25% clears it
    await _set_presence(db_session, w.id, battery_pct=25, source="beacon", server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert await _open_alerts(db_session, w.id, "low_battery") == []


async def test_unauthorized_zone(client, db_session, env2):
    w = env2["worker"]  # PRODUCTION worker
    await _set_presence(db_session, w.id, source="beacon", zone_key=MILL_GATE_KEY,
                        zone_en="Mill Gate", server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    alerts = await _open_alerts(db_session, w.id, "unauthorized_zone")
    assert len(alerts) == 1
    assert alerts[0].detail["zone_dept"] == "SECURITY"
    assert alerts[0].detail["worker_dept"] == "PRODUCTION"
    # back to an own-department zone -> auto-resolve
    await _set_presence(db_session, w.id, source="beacon", zone_key=BOILER_KEY,
                        zone_en="Boiler House", server_ts=now_ist())
    await run_presence_alert_sweep(db_session)
    await db_session.commit()
    assert await _open_alerts(db_session, w.id, "unauthorized_zone") == []


async def test_alert_endpoints_ack_resolve_and_scoping(client, db_session, env2):
    w = env2["worker"]
    await run_presence_alert_sweep(db_session)  # raises gone_dark
    await db_session.commit()

    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/presence/alerts", headers=cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["open_total"] >= 1
    row = next(a for a in body["alerts"] if a["emp_id"] == "P902")
    assert row["alert_type"] == "gone_dark" and row["status"] == "active"

    # dept manager (PRODUCTION == worker's dept) can acknowledge
    prod_mgr = await login(client, PHONES["prod_mgr"])
    r = await client.post(f"/api/presence/alerts/{row['id']}/ack", headers=prod_mgr)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"

    # CGM resolves manually
    r = await client.post(f"/api/presence/alerts/{row['id']}/resolve", headers=cgm)
    assert r.status_code == 200 and r.json()["status"] == "resolved"

    # ack after resolve -> 409
    r = await client.post(f"/api/presence/alerts/{row['id']}/ack", headers=cgm)
    assert r.status_code == 409

    # resolved list shows it with auto_resolved == False (a human resolved it)
    r = await client.get("/api/presence/alerts?status=resolved", headers=cgm)
    assert r.status_code == 200
    resolved_row = next(a for a in r.json()["alerts"] if a["id"] == row["id"])
    assert resolved_row["auto_resolved"] is False

    # a worker can never read alerts
    worker_h = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/presence/alerts", headers=worker_h)
    assert r.status_code == 403


async def test_muster_groups(client, db_session, env2):
    w = env2["worker"]
    cgm = await login(client, PHONES["cgm"])

    await _set_presence(db_session, w.id, source="beacon", zone_key=BOILER_KEY,
                        zone_en="Boiler House", server_ts=now_ist())
    r = await client.get("/api/presence/muster", headers=cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert any(p["emp_id"] == "P902" for p in body["groups"]["inside"])
    assert body["counts"]["inside"] >= 1

    await _set_presence(db_session, w.id, source="gps", inside_geofence=False,
                        zone_key=None, zone_en=None, server_ts=now_ist())
    r = await client.get("/api/presence/muster", headers=cgm)
    assert any(p["emp_id"] == "P902" for p in r.json()["groups"]["outside"])

    # a worker can never take a muster
    worker_h = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/presence/muster", headers=worker_h)
    assert r.status_code == 403


async def _seed_trail(db_session, w):
    """60-min shift: Mill Gate 15m -> Boiler 10m -> GPS outside (capped 10m)."""
    t0 = now_ist() - timedelta(minutes=60)
    att = (await db_session.execute(select(Attendance).where(
        Attendance.employee_id == w.id, Attendance.date == now_ist().date(),
    ))).scalars().first()
    att.punch_in_at = t0
    rows = [
        ("beacon", MILL_GATE_KEY, "Mill Gate", None, 0),
        ("beacon", MILL_GATE_KEY, "Mill Gate", None, 5),
        ("beacon", MILL_GATE_KEY, "Mill Gate", None, 10),
        ("beacon", BOILER_KEY, "Boiler House", None, 15),
        ("beacon", BOILER_KEY, "Boiler House", None, 20),
        ("gps", None, None, False, 25),
    ]
    for source, zkey, zen, inside, mins in rows:
        ts = t0 + timedelta(minutes=mins)
        db_session.add(PresenceHistory(
            id=uuid_mod.uuid4(), employee_id=w.id, source=source, zone_key=zkey,
            zone_en=zen, lat=19.05 if source == "gps" else None,
            lng=74.75 if source == "gps" else None, inside_geofence=inside,
            battery_pct=80, client_ts=ts, server_ts=ts,
        ))
    await db_session.commit()
    return t0


async def test_shift_summary_math(client, db_session, env2):
    w = env2["worker"]
    await _seed_trail(db_session, w)
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/presence/shift-summary", headers=cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    me = next(x for x in body["workers"] if x["emp_id"] == "P902")
    assert me["tracked"] is True
    zones = {z["zone_en"]: z["minutes"] for z in me["zones"]}
    assert zones["Mill Gate"] == 15
    assert zones["Boiler House"] == 10
    assert me["outside_min"] == 10  # last ping covers max 10 min, never the shift end
    assert me["tracked_min"] == 35
    # ~60-min shift, 35 tracked -> coverage ≈ 58%
    assert 54 <= me["coverage_pct"] <= 60
    # localized zone names come from the beacon registry
    assert zones and all(z["zone_mr"] for z in me["zones"])

    # a worker can never read the summary
    worker_h = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/presence/shift-summary", headers=worker_h)
    assert r.status_code == 403

    # future dates are refused
    r = await client.get("/api/presence/shift-summary?date=2099-01-01", headers=cgm)
    assert r.status_code == 400


async def test_timeline_segments_and_scoping(client, db_session, env2):
    w = env2["worker"]
    await _seed_trail(db_session, w)
    cgm = await login(client, PHONES["cgm"])
    r = await client.get(f"/api/presence/timeline?employee_id={w.id}", headers=cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["worker"]["emp_id"] == "P902"
    assert len(body["points"]) == 6
    segs = body["segments"]
    assert [s["kind"] for s in segs] == ["zone", "zone", "gps_outside"]
    assert segs[0]["zone_en"] == "Mill Gate" and segs[0]["minutes"] == 15
    assert segs[1]["zone_en"] == "Boiler House" and segs[1]["minutes"] == 10
    assert segs[2]["minutes"] == 10  # tail capped at 10 min
    assert body["zones"]  # beacon registry for map positions

    # timeline views are audited (individual-trail privacy)
    audit = (await db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "presence.timeline_view",
        AuditEvent.entity_id == str(w.id),
    ))).scalars().first()
    assert audit is not None

    # a worker can never read someone's trail
    worker_h = await login(client, PHONES["w_prod1"])
    r = await client.get(f"/api/presence/timeline?employee_id={w.id}", headers=worker_h)
    assert r.status_code == 403

    # unknown worker -> 404
    r = await client.get(f"/api/presence/timeline?employee_id={uuid_mod.uuid4()}", headers=cgm)
    assert r.status_code == 404
