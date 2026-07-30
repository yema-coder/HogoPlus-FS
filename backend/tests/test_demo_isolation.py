"""Prompt 14: demo showcase bubble — isolation, login matrix, cleanup, purge.

Real users (is_demo=false) must NEVER see demo data; demo users must NEVER see
real data; dept-scoping applies INSIDE the bubble; judge-created rows purge
after 60 min while is_demo_seed rows persist.
"""
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select, text

from app.config import settings
from app.database import SessionLocal
from app.models import Employee, FormSubmission, Incident, Notification
from tests.conftest import DEMO_OTP, NON_WHITELISTED_PHONE, PHONES, login

# demo cast phones used ONLY by this module (deliberately NOT in DEMO_OTP_WHITELIST —
# proves that employee.is_demo alone unlocks the demo OTP)
D_ACC_WORKER = "+919555000001"
D_ACC_MGR = "+919555000101"
D_ENG_MGR = "+919555000107"
D_CGM = "+919555000500"

DEMO_CAST = [
    ("D9001", "Demo Accounts Worker", D_ACC_WORKER, "ACCOUNTS", "Worker"),
    ("D9101", "Demo Accounts Manager", D_ACC_MGR, "ACCOUNTS", "Manager"),
    ("D9107", "Demo Engineering Manager", D_ENG_MGR, "ENGINEERING", "Manager"),
    ("D9500", "Demo CGM", D_CGM, "ADMIN", "CGM"),
]


@pytest_asyncio.fixture(autouse=True)
async def demo_cast():
    async with SessionLocal() as s:
        for emp_id, name, phone, dept, role in DEMO_CAST:
            exists = (
                await s.execute(select(Employee).where(Employee.phone == phone))
            ).scalar_one_or_none()
            if exists is None:
                s.add(Employee(
                    emp_id=emp_id, full_name=name, phone=phone, department_code=dept,
                    designation=name, role_code=role, language_pref="en",
                    shift_swap_eligible=True, onboarding_status="approved",
                    is_active=True, is_demo=True,
                ))
        await s.commit()
    yield


async def _create_incident(client, headers, dept, category="safety", severity="normal"):
    r = await client.post(
        "/api/incidents",
        json={"category": category, "department_code": dept, "severity": severity,
              "photo_key": "demo-test.jpg", "description": "demo isolation test"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- (e) login matrix ----------------

async def test_demo_employee_logs_in_with_demo_otp(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": D_ACC_WORKER, "otp": DEMO_OTP})
    assert r.status_code == 200, r.text
    assert r.json()["employee"]["role_code"] == "Worker"


async def test_real_non_whitelisted_employee_rejected_with_demo_otp(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": NON_WHITELISTED_PHONE, "otp": DEMO_OTP})
    assert r.status_code == 401


async def test_whitelisted_real_admin_still_works(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONES["cgm"], "otp": DEMO_OTP})
    assert r.status_code == 200


async def test_demo_send_otp_never_sends_sms(client):
    r = await client.post("/api/auth/send-otp", json={"phone": D_ACC_WORKER})
    assert r.status_code == 200
    assert r.json()["otp_mode"] == "demo_account"


async def test_registration_guard_blocks_unknown_numbers(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_new_registration", False)
    r = await client.post("/api/auth/send-otp", json={"phone": "+919899000123"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "registration_closed"
    assert all(k in detail for k in ("en", "hi", "mr"))
    # no OTP stored → verify with any code fails as invalid, not accepted
    from app.redis_client import redis_client

    assert not await redis_client.exists("otp:code:+919899000123")
    # known employees still get OTP while registration is closed
    r = await client.post("/api/auth/send-otp", json={"phone": PHONES["w_prod1"]})
    assert r.status_code == 200


# ---------------- (a) cross-bubble invisibility, both directions ----------------

async def test_cross_bubble_invisibility(client, db_session):
    demo_w = await login(client, D_ACC_WORKER)
    inc = await _create_incident(client, demo_w, "ACCOUNTS")
    assert inc["assigned_manager_id"] is not None

    # demo incident routed to the DEMO Accounts manager, not any real employee
    mgr = await db_session.get(Employee, uuid_mod.UUID(inc["assigned_manager_id"]))
    assert mgr.is_demo and mgr.department_code == "ACCOUNTS"

    real_w = await login(client, PHONES["w_prod1"])
    real_inc = await _create_incident(client, real_w, "PRODUCTION", "machine_breakdown")

    real_cgm = await login(client, PHONES["cgm"])
    demo_cgm = await login(client, D_CGM)

    # lists
    real_ids = {i["id"] for i in (await client.get("/api/incidents", headers=real_cgm)).json()}
    demo_ids = {i["id"] for i in (await client.get("/api/incidents", headers=demo_cgm)).json()}
    assert inc["id"] not in real_ids and real_inc["id"] in real_ids
    assert inc["id"] in demo_ids and real_inc["id"] not in demo_ids

    # detail views 404 across the boundary
    assert (await client.get(f"/api/incidents/{inc['id']}", headers=real_cgm)).status_code == 404
    assert (await client.get(f"/api/incidents/{real_inc['id']}", headers=demo_cgm)).status_code == 404

    # dashboard aggregates + feed
    real_over = (await client.get("/api/dashboard/overview", headers=real_cgm)).json()
    demo_over = (await client.get("/api/dashboard/overview", headers=demo_cgm)).json()
    assert inc["id"] not in {f["id"] for f in real_over["incidents"]}
    assert inc["id"] in {f["id"] for f in demo_over["incidents"]}
    assert real_inc["id"] not in {f["id"] for f in demo_over["incidents"]}

    # notification fanout stays inside the class
    demo_mgr = await login(client, D_ACC_MGR)
    mine = (await client.get("/api/notifications/mine", headers=demo_mgr)).json()["items"]
    assert any(n["entity_id"] == inc["id"] for n in mine)
    real_cgm_notifs = (await client.get("/api/notifications/mine", headers=real_cgm)).json()["items"]
    assert not any(n["entity_id"] == inc["id"] for n in real_cgm_notifs)

    # submissions list isolation (demo CGM sees no real submissions)
    subs = (await client.get("/api/submissions", headers=demo_cgm)).json()["items"]
    async with SessionLocal() as s:
        for sub in subs:
            row = await s.get(FormSubmission, uuid_mod.UUID(sub["id"]))
            assert row.is_demo


# ---------------- (b) dept scoping INSIDE the bubble ----------------

async def test_dept_scoping_inside_bubble(client):
    demo_w = await login(client, D_ACC_WORKER)
    inc = await _create_incident(client, demo_w, "ACCOUNTS")

    acc_mgr = await login(client, D_ACC_MGR)
    eng_mgr = await login(client, D_ENG_MGR)
    demo_cgm = await login(client, D_CGM)

    acc_ids = {i["id"] for i in (await client.get("/api/incidents", headers=acc_mgr)).json()}
    eng_ids = {i["id"] for i in (await client.get("/api/incidents", headers=eng_mgr)).json()}
    cgm_ids = {i["id"] for i in (await client.get("/api/incidents", headers=demo_cgm)).json()}
    assert inc["id"] in acc_ids
    assert inc["id"] not in eng_ids
    assert inc["id"] in cgm_ids
    # ENG manager cannot open the detail either
    assert (await client.get(f"/api/incidents/{inc['id']}", headers=eng_mgr)).status_code == 403
    assert (await client.get(f"/api/incidents/{inc['id']}", headers=acc_mgr)).status_code == 200
    # and got no notification for it
    eng_notifs = (await client.get("/api/notifications/mine", headers=eng_mgr)).json()["items"]
    assert not any(n["entity_id"] == inc["id"] for n in eng_notifs)


# ---------------- (c) scheduler + nightly report exclusion ----------------

async def test_escalation_sweep_stays_in_class(client, db_session):
    from app.escalation import run_escalation_sweep

    demo_w = await login(client, D_ACC_WORKER)
    real_w = await login(client, PHONES["w_prod1"])
    demo_inc = await _create_incident(client, demo_w, "ACCOUNTS")
    real_inc = await _create_incident(client, real_w, "PRODUCTION", "machine_breakdown")
    stale = datetime.now(timezone.utc) - timedelta(hours=72)
    await db_session.execute(
        text("UPDATE incidents SET created_at=:t WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"),
        {"t": stale, "a": demo_inc["id"], "b": real_inc["id"]},
    )
    await db_session.commit()

    await run_escalation_sweep(db_session)
    await db_session.commit()

    demo_row = await db_session.get(Incident, uuid_mod.UUID(demo_inc["id"]))
    real_row = await db_session.get(Incident, uuid_mod.UUID(real_inc["id"]))
    demo_cgm_emp = (
        await db_session.execute(select(Employee).where(Employee.phone == D_CGM))
    ).scalar_one()
    real_cgm_emp = (
        await db_session.execute(select(Employee).where(Employee.phone == PHONES["cgm"]))
    ).scalar_one()
    assert demo_row.status == "escalated" and demo_row.escalated_to == demo_cgm_emp.id
    assert real_row.status == "escalated" and real_row.escalated_to == real_cgm_emp.id
    # escalation notifications stayed in class
    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.entity_id == demo_inc["id"])
        )
    ).scalars().all()
    assert notifs and all(n.is_demo and n.recipient_id == demo_cgm_emp.id for n in notifs if n.type == "incident_escalated")


async def test_nightly_report_excludes_demo_rows(client, db_session):
    from datetime import datetime, timezone

    from app.tasks import _report_data

    demo_w = await login(client, D_ACC_WORKER)
    await _create_incident(client, demo_w, "ACCOUNTS", "fire", "critical")
    # _report_data buckets incidents by func.date(created_at) which resolves in
    # the DB session timezone (UTC) — use the UTC date so the test is stable
    # across the 18:30–24:00 UTC window where the IST date is already tomorrow.
    today = datetime.now(timezone.utc).date()
    data = await _report_data(db_session, today)
    real_count = (
        await db_session.execute(
            text("SELECT count(*) FROM incidents WHERE created_at::date = :d AND is_demo = false"),
            {"d": today},
        )
    ).scalar()
    assert data["incidents"]["opened"] == real_count
    assert all(not c.get("is_demo", False) for c in data["incidents"]["critical"])
    demo_critical = (
        await db_session.execute(
            text("SELECT count(*) FROM incidents WHERE created_at::date = :d AND is_demo = true AND severity='critical'"),
            {"d": today},
        )
    ).scalar()
    assert demo_critical >= 1  # demo critical exists but was excluded above


# ---------------- (d) cleanup boundary with mocked clock ----------------

async def test_cleanup_purges_judge_rows_and_spares_seed(client, db_session):
    from app.demo_cleanup import run_demo_cleanup

    demo_w = await login(client, D_ACC_WORKER)
    old_judge = await _create_incident(client, demo_w, "ACCOUNTS")
    fresh_judge = await _create_incident(client, demo_w, "ACCOUNTS")
    seed = await _create_incident(client, demo_w, "ACCOUNTS")
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text("UPDATE incidents SET created_at=:t WHERE id=CAST(:i AS uuid)"),
        {"t": now - timedelta(minutes=90), "i": old_judge["id"]},
    )
    await db_session.execute(
        text("UPDATE incidents SET created_at=:t, is_demo_seed=true WHERE id=CAST(:i AS uuid)"),
        {"t": now - timedelta(hours=50), "i": seed["id"]},
    )
    await db_session.commit()

    # mocked clock: cleanup runs "now" with the 60-minute boundary
    result = await run_demo_cleanup(db_session, now=now, delete_media=False)
    assert result["incidents"] >= 1

    remaining = {
        str(r) for r in (
            await db_session.execute(text("SELECT id FROM incidents WHERE is_demo = true"))
        ).scalars().all()
    }
    assert old_judge["id"] not in remaining      # >60 min → purged
    assert fresh_judge["id"] in remaining        # <60 min → still alive
    assert seed["id"] in remaining               # seed → spared forever


# ---------------- shared factory config is read-only for demo users ----------------

async def test_demo_users_cannot_mutate_shared_config(client):
    demo_cgm = await login(client, D_CGM)
    r = await client.patch(
        "/api/admin/settings", json={"escalation_hours": 5}, headers=demo_cgm
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/admin/test-sms", json={"phone": "+919999999999"}, headers=demo_cgm
    )
    assert r.status_code == 403


# ---------------- (f) purge endpoint ----------------

async def test_purge_endpoint_dry_run_and_permissions(client, db_session):
    demo_w = await login(client, D_ACC_WORKER)
    inc = await _create_incident(client, demo_w, "ACCOUNTS")

    # demo CGM is NOT allowed to purge
    demo_cgm = await login(client, D_CGM)
    r = await client.post("/api/admin/purge-demo-data", json={"dry_run": True}, headers=demo_cgm)
    assert r.status_code == 403

    real_cgm = await login(client, PHONES["cgm"])
    r = await client.post("/api/admin/purge-demo-data", json={"dry_run": True}, headers=real_cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and body["incidents"] >= 1
    # dry run touched nothing
    assert (
        await db_session.execute(text("SELECT count(*) FROM incidents WHERE id=CAST(:i AS uuid)"), {"i": inc["id"]})
    ).scalar() == 1

    # real purge removes judge rows of any age but spares seed rows
    await db_session.execute(
        text("UPDATE incidents SET is_demo_seed=true WHERE is_demo=true AND id != CAST(:i AS uuid)"), {"i": inc["id"]}
    )
    await db_session.commit()
    r = await client.post("/api/admin/purge-demo-data", json={"dry_run": False}, headers=real_cgm)
    assert r.status_code == 200 and r.json()["dry_run"] is False
    left = (
        await db_session.execute(text("SELECT count(*) FROM incidents WHERE id=CAST(:i AS uuid)"), {"i": inc["id"]})
    ).scalar()
    assert left == 0
    seeds_left = (
        await db_session.execute(text("SELECT count(*) FROM incidents WHERE is_demo=true AND is_demo_seed=true"))
    ).scalar()
    assert seeds_left >= 1
    # real data untouched
    real_left = (
        await db_session.execute(text("SELECT count(*) FROM incidents WHERE is_demo=false"))
    ).scalar()
    assert real_left >= 1
