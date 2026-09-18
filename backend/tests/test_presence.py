"""v1.0.25 LIVE WORKER PRESENCE Phase 1 — gates, honesty rules, access scoping,
idempotency, rate limit, freshness thresholds (Live<=6m / Recent<=15m / Stale>15m),
demo isolation and the 30-day purge."""
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import delete, or_, select

from app.models import (
    Attendance,
    AuditEvent,
    BleBeacon,
    Employee,
    FactorySettings,
    PresenceConsent,
    PresenceHistory,
    ShiftAssignment,
    WorkerPresence,
)
from app.routers.presence import CONSENT_VERSION
from app.shift_logic import now_ist
from tests.conftest import PHONES, login, set_otp

W_PHONE = "+919666000111"       # pilot worker (real)
DEMO_CGM_PHONE = "+919666000222"
DEMO_W_PHONE = "+919666000333"
B_UUID = "01122334-4556-6778-899a-abbccddeeff0"
ZONE_KEY = f"{B_UUID}:77:7701"


async def _mk_login(client, phone):
    code = await set_otp(phone)
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def env(client, db_session):
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    worker = Employee(
        emp_id="P901", full_name="Pilot Worker", phone=W_PHONE, department_code="PRODUCTION",
        designation="Worker", role_code="Worker", language_pref="mr", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True,
    )
    demo_cgm = Employee(
        emp_id="D901", full_name="Demo CGM P", phone=DEMO_CGM_PHONE, department_code="ADMIN",
        designation="CGM", role_code="CGM", language_pref="en", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True, is_demo=True,
    )
    demo_w = Employee(
        emp_id="D902", full_name="Demo Worker P", phone=DEMO_W_PHONE, department_code="PRODUCTION",
        designation="Worker", role_code="Worker", language_pref="mr", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True, is_demo=True,
    )
    db_session.add_all([worker, demo_cgm, demo_w])
    await db_session.flush()
    db_session.add(ShiftAssignment(employee_id=worker.id, shift_code="GEN", effective_date=now_ist().date()))
    beacon = BleBeacon(
        beacon_uuid=B_UUID, major=77, minor=7701, zone_label_en="Test Boiler",
        zone_label_hi="टेस्ट बॉयलर", zone_label_mr="टेस्ट बॉयलर", is_active=True,
    )
    db_session.add(beacon)
    fs.live_presence_enabled = True
    fs.presence_pilot_emp_ids = "P901"
    await db_session.commit()
    ids = [worker.id, demo_cgm.id, demo_w.id]
    yield {"worker": worker, "demo_cgm": demo_cgm, "demo_w": demo_w,
           "fs_lat": fs.factory_lat, "fs_lng": fs.factory_lng}
    # -------- teardown: restore baseline --------
    demo_ids = [
        e for e in (
            await db_session.execute(select(Employee.id).where(Employee.is_demo.is_(True)))
        ).scalars()
    ]
    all_ids = list(set(ids + demo_ids))
    for model in (WorkerPresence, PresenceHistory, PresenceConsent):
        await db_session.execute(delete(model).where(model.employee_id.in_(all_ids)))
    await db_session.execute(delete(Attendance).where(
        Attendance.employee_id.in_(all_ids), Attendance.date == now_ist().date()))
    await db_session.execute(delete(AuditEvent).where(or_(
        AuditEvent.actor_id.in_(ids),
        AuditEvent.action.in_(["presence.dashboard_view", "presence.settings_changed",
                               "presence.demo_simulated", "presence.consent_granted"]),
    )))
    await db_session.execute(delete(ShiftAssignment).where(ShiftAssignment.employee_id.in_(ids)))
    for e_id in ids:
        e = await db_session.get(Employee, e_id)
        if e:
            await db_session.delete(e)
    b = (await db_session.execute(select(BleBeacon).where(BleBeacon.beacon_uuid == B_UUID))).scalars().first()
    if b:
        await db_session.delete(b)
    fs2 = (await db_session.execute(select(FactorySettings))).scalars().first()
    fs2.live_presence_enabled = False
    fs2.presence_pilot_emp_ids = ""
    await db_session.commit()


def _ping(pid, **kw):
    return {"client_ping_id": f"test-ping-{pid:04d}", **kw}


async def _punch_in(client, headers, env):
    r = await client.post("/api/attendance/punch-in", headers=headers, json={
        "gps_lat": env["fs_lat"], "gps_lng": env["fs_lng"], "selfie_key": "p901.jpg",
    })
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- gates

async def test_flag_off_refuses_everything(client, db_session, env):
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    fs.live_presence_enabled = False
    await db_session.commit()
    w = await _mk_login(client, W_PHONE)
    r = await client.post("/api/presence/ping", headers=w,
                          json={"pings": [_ping(1, source="gps", lat=19.0, lng=74.0)]})
    assert r.status_code == 403 and r.json()["detail"] == "presence_disabled"
    mgr = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/presence/live", headers=mgr)
    assert r.status_code == 200 and r.json()["enabled"] is False


async def test_pilot_consent_and_shift_gates(client, db_session, env):
    w = await _mk_login(client, W_PHONE)
    # in pilot, but no consent yet
    r = await client.post("/api/presence/ping", headers=w,
                          json={"pings": [_ping(2, source="gps", lat=19.0, lng=74.0)]})
    assert r.status_code == 403 and r.json()["detail"] == "consent_required"
    # consent with wrong version rejected
    r = await client.post("/api/presence/consent", headers=w, json={"version": "9.9", "lang": "mr"})
    assert r.status_code == 400
    r = await client.post("/api/presence/consent", headers=w,
                          json={"version": CONSENT_VERSION, "lang": "mr"})
    assert r.status_code == 200
    # consented but NOT punched in -> refused (zero tracking outside shift)
    r = await client.post("/api/presence/ping", headers=w,
                          json={"pings": [_ping(3, source="gps", lat=19.0, lng=74.0)]})
    assert r.status_code == 409 and r.json()["detail"] == "not_punched_in"
    # a worker NOT in the pilot list is refused even with everything else
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    fs.presence_pilot_emp_ids = ""
    await db_session.commit()
    r = await client.post("/api/presence/ping", headers=w,
                          json={"pings": [_ping(4, source="gps", lat=19.0, lng=74.0)]})
    assert r.status_code == 403 and r.json()["detail"] == "not_in_pilot"


# ------------------------------------------------- happy path + honesty rules

async def test_zone_ping_shows_in_zone_and_freshness_live(client, db_session, env):
    w = await _mk_login(client, W_PHONE)
    await client.post("/api/presence/consent", headers=w, json={"version": CONSENT_VERSION, "lang": "mr"})
    await _punch_in(client, w, env)
    r = await client.post("/api/presence/ping", headers=w, json={"pings": [
        _ping(10, source="beacon", zone_key=ZONE_KEY, battery_pct=77, app_version="1.0.25"),
    ]})
    assert r.status_code == 200 and r.json()["accepted"] == 1

    mgr = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/presence/live", headers=mgr)
    body = r.json()
    assert body["enabled"] is True
    me = next(x for x in body["workers"] if x["emp_id"] == "P901")
    assert me["status"] == "in_zone" and me["zone_en"] == "Test Boiler"
    assert me["freshness"] == "live" and me["battery_pct"] == 77
    assert body["counts"]["in_zone"] >= 1 and body["counts"]["tracking"] >= 1
    zone = next(z for z in body["zones"] if z["key"] == ZONE_KEY)
    assert zone["count"] == 1 and zone["name_mr"] == "टेस्ट बॉयलर"
    # dashboard view audited (throttled)
    n = (await db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "presence.dashboard_view"))).scalars().all()
    assert len(n) >= 1


async def test_idempotency_and_rate_limit(client, db_session, env):
    w = await _mk_login(client, W_PHONE)
    await client.post("/api/presence/consent", headers=w, json={"version": CONSENT_VERSION, "lang": "mr"})
    await _punch_in(client, w, env)
    dup = _ping(20, source="beacon", zone_key=ZONE_KEY)
    r = await client.post("/api/presence/ping", headers=w, json={"pings": [dup, dup]})
    assert r.status_code == 200
    assert r.json()["accepted"] == 1 and r.json()["duplicates"] == 1
    rows = (await db_session.execute(select(PresenceHistory).where(
        PresenceHistory.employee_id == env["worker"].id))).scalars().all()
    assert len(rows) == 1
    # second batch inside the 20s window -> 429
    r = await client.post("/api/presence/ping", headers=w, json={"pings": [_ping(21, source="gps", lat=1, lng=1)]})
    assert r.status_code == 429


async def test_gps_outside_geofence_and_stationary_worker_stays_live(client, db_session, env):
    w = await _mk_login(client, W_PHONE)
    await client.post("/api/presence/consent", headers=w, json={"version": CONSENT_VERSION, "lang": "mr"})
    await _punch_in(client, w, env)
    r = await client.post("/api/presence/ping", headers=w, json={"pings": [
        _ping(30, source="gps", lat=env["fs_lat"] + 0.05, lng=env["fs_lng"] + 0.05, accuracy_m=15),
    ]})
    assert r.status_code == 200
    mgr = await login(client, PHONES["time_mgr"])
    me = next(x for x in (await client.get("/api/presence/live", headers=mgr)).json()["workers"]
              if x["emp_id"] == "P901")
    assert me["status"] == "gps_outside" and me["inside_geofence"] is False

    # stationary worker: last heartbeat 5.5 min ago must still be LIVE (owner rule 1)
    me_row = (await db_session.execute(select(WorkerPresence).where(
        WorkerPresence.employee_id == env["worker"].id))).scalar_one()
    me_row.server_ts = now_ist() - timedelta(seconds=330)
    await db_session.commit()
    me = next(x for x in (await client.get("/api/presence/live", headers=mgr)).json()["workers"]
              if x["emp_id"] == "P901")
    assert me["freshness"] == "live" and me["status"] == "gps_outside"
    # 10 min ago -> Recent (still a real position) ; 20 min -> stale == no_signal
    me_row.server_ts = now_ist() - timedelta(minutes=10)
    await db_session.commit()
    me = next(x for x in (await client.get("/api/presence/live", headers=mgr)).json()["workers"]
              if x["emp_id"] == "P901")
    assert me["freshness"] == "recent" and me["status"] == "gps_outside"
    me_row.server_ts = now_ist() - timedelta(minutes=20)
    await db_session.commit()
    me = next(x for x in (await client.get("/api/presence/live", headers=mgr)).json()["workers"]
              if x["emp_id"] == "P901")
    assert me["freshness"] == "stale" and me["status"] == "no_signal"


async def test_stopped_and_not_tracked_are_separate_statuses(client, db_session, env):
    w = await _mk_login(client, W_PHONE)
    await client.post("/api/presence/consent", headers=w, json={"version": CONSENT_VERSION, "lang": "mr"})
    await _punch_in(client, w, env)
    r = await client.post("/api/presence/ping", headers=w, json={"pings": [_ping(40, source="stopped")]})
    assert r.status_code == 200
    mgr = await login(client, PHONES["time_mgr"])
    body = (await client.get("/api/presence/live", headers=mgr)).json()
    me = next(x for x in body["workers"] if x["emp_id"] == "P901")
    assert me["status"] == "stopped"
    assert body["counts"]["stopped"] >= 1

    # a punched-in worker who is NOT in the pilot shows "not_tracked", never "no_signal"
    wp = await login(client, PHONES["w_prod1"])
    await client.post("/api/attendance/punch-in", headers=wp, json={
        "gps_lat": env["fs_lat"], "gps_lng": env["fs_lng"], "selfie_key": "np1.jpg"})
    body = (await client.get("/api/presence/live", headers=mgr)).json()
    other = next((x for x in body["workers"] if x["status"] == "not_tracked"), None)
    assert other is not None and body["counts"]["not_tracked"] >= 1


# ---------------------------------------------------------------- access

async def test_access_scoping(client, env):
    # a worker may never open the dashboard
    w = await _mk_login(client, W_PHONE)
    assert (await client.get("/api/presence/live", headers=w)).status_code == 403
    # security manager sees everything
    sec = await login(client, PHONES["sec_mgr"])
    assert (await client.get("/api/presence/live", headers=sec)).json()["scope"] == "all"
    # a PRODUCTION manager is scoped to PRODUCTION only
    prod = await login(client, PHONES["prod_mgr"])
    body = (await client.get("/api/presence/live", headers=prod)).json()
    assert body["scope"] == "PRODUCTION"
    assert all(x["department_code"] == "PRODUCTION" for x in body["workers"])
    # settings endpoint: workers refused, CGM allowed
    assert (await client.get("/api/presence/settings", headers=w)).status_code == 403
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/presence/settings", headers=cgm)
    assert r.status_code == 200 and r.json()["consent_version"] == CONSENT_VERSION


async def test_demo_simulation_is_isolated(client, db_session, env):
    demo_cgm = await _mk_login(client, DEMO_CGM_PHONE)
    r = await client.post("/api/presence/demo-simulate", headers=demo_cgm)
    assert r.status_code == 200, r.text
    # demo viewer sees the simulated cast
    body = (await client.get("/api/presence/live", headers=demo_cgm)).json()
    assert body["enabled"] is True and body["counts"]["on_shift"] >= 1
    # real viewer NEVER sees demo workers
    mgr = await login(client, PHONES["time_mgr"])
    real = (await client.get("/api/presence/live", headers=mgr)).json()
    demo_ids = {x["emp_id"] for x in body["workers"]}
    assert all(x["emp_id"] not in demo_ids for x in real["workers"])


async def test_purge_deletes_only_old_history(client, db_session, env):
    import uuid as uuid_mod

    from app.tasks import _presence_purge_async
    old = PresenceHistory(id=uuid_mod.uuid4(), employee_id=env["worker"].id, source="gps",
                          lat=1.0, lng=1.0, server_ts=now_ist() - timedelta(days=35))
    fresh = PresenceHistory(id=uuid_mod.uuid4(), employee_id=env["worker"].id, source="gps",
                            lat=1.0, lng=1.0, server_ts=now_ist() - timedelta(days=2))
    db_session.add_all([old, fresh])
    await db_session.commit()
    deleted = await _presence_purge_async()
    assert deleted >= 1
    left = (await db_session.execute(select(PresenceHistory).where(
        PresenceHistory.employee_id == env["worker"].id))).scalars().all()
    assert len(left) == 1 and left[0].id == fresh.id
