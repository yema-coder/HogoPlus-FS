"""v1.0.27 Broadcast / Send-Notification engine tests."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.models import Broadcast, BroadcastReceipt, Employee, Notification
from tests.conftest import PHONES, login


async def _enable_flag(client, rate=10):
    hdr = await login(client, PHONES["cgm"])
    r = await client.patch(
        "/api/admin/settings",
        json={"broadcasts_enabled": True, "broadcast_rate_per_hour": rate},
        headers=hdr,
    )
    assert r.status_code == 200, r.text


async def _disable_flag(client):
    hdr = await login(client, PHONES["cgm"])
    await client.patch("/api/admin/settings", json={"broadcasts_enabled": False}, headers=hdr)


# ---------------- role gating ----------------

@pytest.mark.asyncio
async def test_worker_cannot_access(client):
    hdr = await login(client, PHONES["w_prod1"])
    assert (await client.get("/api/broadcasts/meta", headers=hdr)).status_code == 403
    assert (await client.post("/api/broadcasts/preview", json={"audience_type": "all"}, headers=hdr)).status_code == 403


@pytest.mark.asyncio
async def test_plain_manager_forbidden_but_time_office_ok(client):
    # a regular (non-Time-Office) manager must NOT see it
    hdr_mgr = await login(client, PHONES["prod_mgr"])
    assert (await client.get("/api/broadcasts/meta", headers=hdr_mgr)).status_code == 403
    # Time Office manager + CGM may
    for phone in (PHONES["time_mgr"], PHONES["cgm"]):
        hdr = await login(client, phone)
        assert (await client.get("/api/broadcasts/meta", headers=hdr)).status_code == 200


# ---------------- audience resolution ----------------

@pytest.mark.asyncio
async def test_preview_counts(client):
    hdr = await login(client, PHONES["cgm"])
    r = await client.post("/api/broadcasts/preview", json={"audience_type": "role", "roles": ["Worker"]}, headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["recipient_count"] >= 8  # many seeded workers
    assert body["installed_count"] + body["no_token_count"] == body["recipient_count"]
    # empty selection → 0
    r2 = await client.post("/api/broadcasts/preview", json={"audience_type": "department", "departments": []}, headers=hdr)
    assert r2.json()["recipient_count"] == 0


# ---------------- flag gate ----------------

@pytest.mark.asyncio
async def test_create_blocked_when_flag_off(client):
    await _disable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "all", "title_mr": "चाचणी", "body_mr": "संदेश"},
        headers=hdr,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "broadcasts_disabled"


@pytest.mark.asyncio
async def test_test_send_works_even_when_flag_off(client):
    await _disable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts/test",
        json={"audience_type": "employees", "title_mr": "चाचणी", "body_mr": "माझ्या फोनवर"},
        headers=hdr,
    )
    assert r.status_code == 200
    assert r.json()["is_test"] is True
    assert r.json()["recipient_count"] == 1


# ---------------- send + inbox-is-source-of-truth ----------------

@pytest.mark.asyncio
async def test_send_creates_inbox_rows_and_receipts(client, db_session):
    await _enable_flag(client)
    # give ONE worker a push token so we see a "sent" receipt
    w = (await db_session.execute(select(Employee).where(Employee.phone == PHONES["w_prod1"]))).scalar_one()
    w.expo_push_token = "ExponentPushToken[test-abc]"
    await db_session.commit()

    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "role", "roles": ["Worker"], "title_mr": "सुरक्षा", "body_mr": "बैठक आहे", "priority": "important"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    bc = r.json()
    assert bc["recipient_count"] >= 8
    assert bc["sent_count"] >= 1  # the tokened worker
    assert bc["installed_count"] >= 1

    bid = uuid.UUID(bc["id"])
    # inbox row created for EVERY recipient (source of truth)
    inbox = (await db_session.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.entity_type == "broadcast", Notification.entity_id == str(bid))
    )).scalar()
    assert inbox == bc["recipient_count"]
    # a receipt per recipient
    rc = (await db_session.execute(
        select(func.count()).select_from(BroadcastReceipt).where(BroadcastReceipt.broadcast_id == bid)
    )).scalar()
    assert rc == bc["recipient_count"]
    # worker with NO token counted as no_token, never silently dropped
    assert bc["no_token_count"] >= 1


@pytest.mark.asyncio
async def test_no_recipients_422(client):
    await _enable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "department", "departments": ["CIVIL"], "title_mr": "x", "body_mr": "y"},
        headers=hdr,
    )
    # CIVIL has no seeded employees
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_recipients"


# ---------------- duplicate guard + rate limit ----------------

@pytest.mark.asyncio
async def test_duplicate_warning_then_force(client):
    await _enable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    payload = {"audience_type": "all", "title_mr": "डुप्लिकेट", "body_mr": "तोच संदेश", "priority": "normal"}
    r1 = await client.post("/api/broadcasts", json=payload, headers=hdr)
    assert r1.status_code == 200
    r2 = await client.post("/api/broadcasts", json=payload, headers=hdr)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "duplicate_recent"
    r3 = await client.post("/api/broadcasts", json={**payload, "force": True}, headers=hdr)
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit(client):
    await _enable_flag(client, rate=2)
    hdr = await login(client, PHONES["cgm"])
    codes = []
    for i in range(3):
        r = await client.post(
            "/api/broadcasts",
            json={"audience_type": "all", "title_mr": f"दर {i}", "body_mr": f"संदेश {i}", "force": True},
            headers=hdr,
        )
        codes.append(r.status_code)
    assert codes[-1] == 429
    assert codes[:2] == [200, 200]


# ---------------- scheduling survives a restart (DB-state driven) ----------------

@pytest.mark.asyncio
async def test_scheduled_send_fires_from_sweep(client, db_session):
    await _enable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "department", "departments": ["PRODUCTION"],
              "title_mr": "नियोजित", "body_mr": "उद्या", "scheduled_at": when},
        headers=hdr,
    )
    assert r.status_code == 200
    bc = r.json()
    assert bc["status"] == "scheduled"
    bid = uuid.UUID(bc["id"])
    # no inbox rows yet
    pre = (await db_session.execute(
        select(func.count()).select_from(Notification).where(Notification.entity_id == str(bid))
    )).scalar()
    assert pre == 0
    # simulate the scheduled time arriving (DB state, not an in-memory timer)
    await db_session.execute(
        text("UPDATE broadcasts SET scheduled_at = now() - interval '1 minute' WHERE id = :i"),
        {"i": str(bid)},
    )
    await db_session.commit()
    from app.routers.broadcasts import run_broadcast_schedule_sweep
    res = await run_broadcast_schedule_sweep()
    assert res["scheduled_sent"] >= 1
    await db_session.commit()
    sent = await db_session.get(Broadcast, bid)
    await db_session.refresh(sent)
    assert sent.status == "sent"
    post = (await db_session.execute(
        select(func.count()).select_from(Notification).where(Notification.entity_id == str(bid))
    )).scalar()
    assert post == sent.recipient_count >= 1


# ---------------- invalid token cleanup (DeviceNotRegistered) ----------------

@pytest.mark.asyncio
async def test_invalid_token_cleanup(client, db_session, monkeypatch):
    await _enable_flag(client)
    w = (await db_session.execute(select(Employee).where(Employee.phone == PHONES["w_eng"]))).scalar_one()
    w.expo_push_token = "ExponentPushToken[dead]"
    await db_session.commit()

    async def fake_send(messages):
        return [{"status": "error", "message": "bad", "details": {"error": "DeviceNotRegistered"}} for _ in messages]

    monkeypatch.setattr("app.routers.broadcasts.expo_send_messages", fake_send)
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "department", "departments": ["ENGINEERING"], "title_mr": "x", "body_mr": "y"},
        headers=hdr,
    )
    assert r.status_code == 200
    # token cleared → counted as no_token, not failed/sent
    await db_session.refresh(w)
    assert w.expo_push_token is None
    assert r.json()["no_token_count"] >= 1


# ---------------- receipt sweep marks delivered ----------------

@pytest.mark.asyncio
async def test_receipt_sweep_marks_delivered(client, db_session, monkeypatch):
    await _enable_flag(client)
    w = (await db_session.execute(select(Employee).where(Employee.phone == PHONES["w_prod2"]))).scalar_one()
    w.expo_push_token = "ExponentPushToken[live]"
    await db_session.commit()
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "employees", "employee_ids": [str(w.id)], "title_mr": "x", "body_mr": "y"},
        headers=hdr,
    )
    bid = uuid.UUID(r.json()["id"])
    # the sent receipt has a TEST ticket; age it past the 3-min cutoff
    rc = (await db_session.execute(
        select(BroadcastReceipt).where(BroadcastReceipt.broadcast_id == bid, BroadcastReceipt.status == "sent")
    )).scalar_one()
    await db_session.execute(
        text("UPDATE broadcast_receipts SET updated_at = now() - interval '10 minutes' WHERE id = :i"),
        {"i": str(rc.id)},
    )
    await db_session.commit()

    async def fake_receipts(ids):
        return {i: {"status": "ok"} for i in ids}

    monkeypatch.setattr("app.routers.broadcasts.expo_fetch_receipts", fake_receipts)
    from app.routers.broadcasts import run_broadcast_receipt_sweep
    res = await run_broadcast_receipt_sweep()
    assert res.get("receipts_updated", 0) >= 1
    await db_session.commit()
    bc = await db_session.get(Broadcast, bid)
    await db_session.refresh(bc)
    assert bc.delivered_count >= 1


# ---------------- resend to failed ----------------

@pytest.mark.asyncio
async def test_resend_to_failed(client, db_session):
    await _enable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/broadcasts",
        json={"audience_type": "department", "departments": ["PRODUCTION"], "title_mr": "x", "body_mr": "y"},
        headers=hdr,
    )
    bid = r.json()["id"]
    # give one no_token recipient a token, then resend-to-failed
    rc = (await db_session.execute(
        select(BroadcastReceipt).where(BroadcastReceipt.broadcast_id == uuid.UUID(bid), BroadcastReceipt.status == "no_token")
    )).scalars().first()
    emp = await db_session.get(Employee, rc.employee_id)
    emp.expo_push_token = "ExponentPushToken[resend]"
    await db_session.commit()
    r2 = await client.post(f"/api/broadcasts/{bid}/resend", json={"failed_only": True}, headers=hdr)
    assert r2.status_code == 200
    assert r2.json()["sent_count"] >= 1


# ---------------- history + detail + opened ----------------

@pytest.mark.asyncio
async def test_history_and_opened(client, db_session):
    await _enable_flag(client)
    hdr = await login(client, PHONES["cgm"])
    await client.post(
        "/api/broadcasts",
        json={"audience_type": "all", "title_mr": "इतिहास चाचणी", "body_mr": "संदेश", "priority": "emergency"},
        headers=hdr,
    )
    lst = await client.get("/api/broadcasts?type=emergency", headers=hdr)
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert any(i["title_mr"] == "इतिहास चाचणी" for i in items)
    bid = items[0]["id"]
    # detail
    det = await client.get(f"/api/broadcasts/{bid}", headers=hdr)
    assert det.status_code == 200
    assert "failed_recipients" in det.json()
    # opened ping (mark one recipient's receipt opened)
    rc = (await db_session.execute(
        select(BroadcastReceipt).where(BroadcastReceipt.broadcast_id == uuid.UUID(bid))
    )).scalars().first()
    emp = await db_session.get(Employee, rc.employee_id)
    hdr_emp = await login(client, emp.phone)
    op = await client.post("/api/broadcasts/receipt-opened", json={"broadcast_id": bid}, headers=hdr_emp)
    assert op.status_code == 200


@pytest.mark.asyncio
async def test_meta_zones(client):
    hdr = await login(client, PHONES["cgm"])
    r = await client.get("/api/broadcasts/meta", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert "zones" in body and isinstance(body["zones"], list)
    assert body["enabled"] in (True, False)
