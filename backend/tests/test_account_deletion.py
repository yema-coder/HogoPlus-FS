"""v1.0.25 App-Store compliance — in-app account deletion.

Rules under test:
 - demo/reviewer accounts are PROTECTED (409, audited nothing destroyed)
 - OTP re-verify: wrong code counts down, 5 fails lock for 15 min
 - happy path: personal data DELETED (name, phone, selfies, face ref, push token,
   presence trail, consents, password), legal records KEPT anonymised
   ("Deleted user #emp_id", attendance rows remain, selfie_key='deleted'),
 - sessions die: old access token 401s right after deletion (is_active=False)
 - hosted privacy policy is public at /api/legal/privacy (EN + MR)
"""
import hashlib

import pytest_asyncio
from sqlalchemy import delete, select

from app.models import (
    Attendance,
    AuditEvent,
    Employee,
    PresenceConsent,
    PresenceHistory,
    WorkerPresence,
)
from app.redis_client import redis_client
from app.shift_logic import now_ist
from tests.conftest import set_otp

DEL_PHONE = "+919666000444"
DEL_DEMO_PHONE = "+919666000555"


async def _mk_login(client, phone):
    code = await set_otp(phone)
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def env(client, db_session):
    worker = Employee(
        emp_id="X901", full_name="Delete Me Worker", phone=DEL_PHONE, department_code="PRODUCTION",
        designation="Worker", role_code="Worker", language_pref="mr", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True,
        reference_selfie_key="ref-x901.jpg", expo_push_token="ExpoPushToken[x901]",
    )
    demo = Employee(
        emp_id="X902", full_name="Demo Protected", phone=DEL_DEMO_PHONE, department_code="ADMIN",
        designation="CGM", role_code="CGM", language_pref="en", shift_swap_eligible=False,
        onboarding_status="approved", is_active=True, is_demo=True,
    )
    db_session.add_all([worker, demo])
    await db_session.flush()
    db_session.add(Attendance(
        employee_id=worker.id, date=now_ist().date(), punch_in_at=now_ist(),
        selfie_key="att-x901.jpg", verification_level="verified", shift_code="GEN",
    ))
    db_session.add(PresenceConsent(employee_id=worker.id, version="1.0", lang="mr", granted_at=now_ist()))
    db_session.add(WorkerPresence(employee_id=worker.id, source="gps", server_ts=now_ist()))
    await db_session.commit()
    ids = [worker.id, demo.id]
    yield {"worker": worker, "demo": demo}
    for model in (WorkerPresence, PresenceHistory, PresenceConsent):
        await db_session.execute(delete(model).where(model.employee_id.in_(ids)))
    await db_session.execute(delete(Attendance).where(Attendance.employee_id.in_(ids)))
    await db_session.execute(delete(AuditEvent).where(AuditEvent.actor_id.in_(ids)))
    for e_id in ids:
        e = await db_session.get(Employee, e_id)
        if e:
            await db_session.delete(e)
    await db_session.commit()


async def _arm_otp(employee_id, code="654321"):
    key = f"acctdel:otp:{employee_id}"
    await redis_client.delete(key)
    await redis_client.setex(key, 600, hashlib.sha256(code.encode()).hexdigest())
    return code


async def test_demo_account_protected(client, env):
    h = await _mk_login(client, DEL_DEMO_PHONE)
    r = await client.post("/api/auth/delete-account/request", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "demo_protected"
    r = await client.post("/api/auth/delete-account/confirm", headers=h, json={"otp": "123456"})
    assert r.status_code == 409


async def test_request_sends_otp_and_rate_limits(client, env):
    h = await _mk_login(client, DEL_PHONE)
    r = await client.post("/api/auth/delete-account/request", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] == 600
    # second request while an OTP is live → 429
    r2 = await client.post("/api/auth/delete-account/request", headers=h)
    assert r2.status_code == 429


async def test_wrong_otp_locks_after_five(client, env):
    h = await _mk_login(client, DEL_PHONE)
    await _arm_otp(env["worker"].id)
    for i in range(4):
        r = await client.post("/api/auth/delete-account/confirm", headers=h, json={"otp": "000000"})
        assert r.status_code == 401, f"attempt {i}: {r.text}"
    r = await client.post("/api/auth/delete-account/confirm", headers=h, json={"otp": "000000"})
    assert r.status_code == 429  # locked
    # even the RIGHT code is refused while locked
    r = await client.post("/api/auth/delete-account/confirm", headers=h, json={"otp": "654321"})
    assert r.status_code == 429


async def test_delete_happy_path(client, env, db_session):
    worker = env["worker"]
    worker_id, worker_emp_id = worker.id, worker.emp_id
    h = await _mk_login(client, DEL_PHONE)
    code = await _arm_otp(worker_id)
    r = await client.post("/api/auth/delete-account/confirm", headers=h, json={"otp": code})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"

    # old token is dead immediately (is_active=False on both token paths)
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 401

    db_session.expire_all()
    e = await db_session.get(Employee, worker_id)
    assert e.full_name == f"Deleted user #{worker_emp_id}"
    assert e.phone is None
    assert e.reference_selfie_key is None
    assert e.expo_push_token is None
    assert e.password_hash is None
    assert e.is_active is False

    # legal attendance record KEPT, selfie anonymised
    att = (
        await db_session.execute(select(Attendance).where(Attendance.employee_id == worker_id))
    ).scalars().all()
    assert len(att) == 1
    assert att[0].selfie_key == "deleted"

    # presence trail + consents hard-deleted
    for model in (WorkerPresence, PresenceHistory, PresenceConsent):
        rows = (
            await db_session.execute(select(model).where(model.employee_id == worker_id))
        ).scalars().all()
        assert rows == []

    # deletion audited
    audits = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.actor_id == worker_id, AuditEvent.action == "account.deleted")
        )
    ).scalars().all()
    assert len(audits) == 1

    # the dead login phone falls into the fresh-registration path, not this account
    r = await client.post("/api/auth/verify-otp", json={"phone": DEL_PHONE, "otp": await set_otp(DEL_PHONE)})
    assert r.status_code == 200
    assert r.json()["is_new"] is True


async def test_privacy_policy_public(client):
    r = await client.get("/api/legal/privacy")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Delete my account" in body or "Profile" in body
    assert "गोपनीयता धोरण" in body  # Marathi section present
    assert "30 days" in body  # live-location purge disclosed
