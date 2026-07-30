"""v1.0.22 batch tests (live local Postgres + Redis):

1. Shift-end punch-out NUDGE escalation — reminder (existing) then, hours later,
   flag for Time Office (flagged_reason='no_punch_out'). NEVER auto-writes a
   punch-out time; verification_level of the punch-in is NEVER touched; a real
   late punch-out self-resolves the flag; the worker can dispute the flagged day.
   Overnight (B) shifts whose attendance row is dated YESTERDAY are covered.
2. Shift-swap SELECT ... FOR UPDATE — two truly CONCURRENT decide/respond calls:
   exactly one wins, assignments are applied exactly once.
3. Offline outbox idempotency — incidents + form submissions replayed with the
   same client_uuid return the SAME row (pattern shipped for vehicles in 0013).
"""
import asyncio
import uuid as uuid_mod
from datetime import date, timedelta

from sqlalchemy import text

from app.config import settings
from app.shift_logic import now_ist
from app.tasks import _punchout_reminder_async
from tests.conftest import PHONES, employee_id_by_phone, login


async def _me_id(client, headers) -> str:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


async def _clean_attendance(db_session, emp_id: str) -> None:
    """Remove this employee's attendance (and dependent disputes) so the test
    owns the only open row — immune to suite ordering."""
    await db_session.execute(
        text("DELETE FROM attendance_regularizations WHERE employee_id=:e"), {"e": emp_id}
    )
    await db_session.execute(text("DELETE FROM attendance WHERE employee_id=:e"), {"e": emp_id})
    await db_session.commit()


async def _insert_open_punch(db_session, emp_id: str, day, flagged_reason=None) -> str:
    row_id = str(uuid_mod.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO attendance (id, employee_id, date, punch_in_at, verification_level, "
            "flagged_reason, is_late, gps_verified, selfie_key) "
            "VALUES (:i, :e, :d, now(), 'verified', :fr, false, true, 's.jpg')"
        ),
        {"i": row_id, "e": emp_id, "d": day, "fr": flagged_reason},
    )
    await db_session.commit()
    return row_id


async def _isolate_sweep(db_session, emp_id: str) -> list:
    """Temporarily close everyone else's open punches so a sweep in THIS test only
    touches the test's own rows (redis guards are flushed per-test, so a sweep here
    would otherwise notify/flag other tests' workers and skew their state).
    Returns the row ids to restore with _restore_sweep."""
    rows = (
        await db_session.execute(
            text(
                "UPDATE attendance SET punch_out_at = now() "
                "WHERE punch_out_at IS NULL AND employee_id != :e RETURNING id"
            ),
            {"e": emp_id},
        )
    ).scalars().all()
    await db_session.commit()
    return list(rows)


async def _restore_sweep(db_session, ids: list) -> None:
    if ids:
        await db_session.execute(
            text("UPDATE attendance SET punch_out_at = NULL WHERE id = ANY(:ids)"), {"ids": ids}
        )
        await db_session.commit()


# =====================================================================
# 1. Punch-out nudge escalation
# =====================================================================

async def test_nudge_reminder_then_flag_never_auto_punches(client, db_session, monkeypatch):
    w = await login(client, PHONES["w_att3"])
    emp_id = await _me_id(client, w)
    await _clean_attendance(db_session, emp_id)
    parked = await _isolate_sweep(db_session, emp_id)
    today = now_ist().date()
    att_id = await _insert_open_punch(db_session, emp_id, today)

    monkeypatch.setattr(settings, "punchout_flag_after_hours", 0)
    fake_now = now_ist().replace(hour=23, minute=45)  # long after GEN shift end (17:30)

    try:
        out1 = await _punchout_reminder_async(now=fake_now)
        assert out1["sent"] >= 1 and out1["flagged"] >= 1

        row = (
            await db_session.execute(
                text("SELECT punch_out_at, verification_level, flagged_reason FROM attendance WHERE id=:i"),
                {"i": att_id},
            )
        ).first()
        assert row.punch_out_at is None  # NEVER invents a punch-out time
        assert row.verification_level == "verified"  # punch-in verification untouched
        assert row.flagged_reason == "no_punch_out"

        for typ in ("punchout_reminder", "punchout_flagged"):
            n = (
                await db_session.execute(
                    text("SELECT COUNT(*) FROM notifications WHERE recipient_id=:e AND type=:t"),
                    {"e": emp_id, "t": typ},
                )
            ).scalar()
            assert n == 1, f"{typ}: expected exactly 1, got {n}"

        audits = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE action='attendance.no_punch_out_flagged' "
                     "AND entity_id=:i"), {"i": att_id},
            )
        ).scalar()
        assert audits == 1

        # second sweep: redis guard blocks the reminder, reason-check blocks a re-flag
        await _punchout_reminder_async(now=fake_now)
        for typ in ("punchout_reminder", "punchout_flagged"):
            n = (
                await db_session.execute(
                    text("SELECT COUNT(*) FROM notifications WHERE recipient_id=:e AND type=:t"),
                    {"e": emp_id, "t": typ},
                )
            ).scalar()
            assert n == 1, f"{typ}: repeated on second sweep"
    finally:
        await _restore_sweep(db_session, parked)


async def test_nudge_covers_overnight_shift_dated_yesterday(client, db_session, monkeypatch):
    # w_prod2's baseline is B (16:00→00:00, overnight): the attendance row is dated
    # YESTERDAY when the shift ends after midnight — the old today-only sweep missed it.
    w = await login(client, PHONES["w_prod2"])
    emp_id = await _me_id(client, w)
    await _clean_attendance(db_session, emp_id)
    parked = await _isolate_sweep(db_session, emp_id)
    yesterday = now_ist().date() - timedelta(days=1)
    att_id = await _insert_open_punch(db_session, emp_id, yesterday)

    monkeypatch.setattr(settings, "punchout_flag_after_hours", 0)
    # B ended today 00:00 IST; sweep at 03:00 today is past end+15min
    fake_now = now_ist().replace(hour=3, minute=0)
    try:
        out = await _punchout_reminder_async(now=fake_now)
        assert out["flagged"] >= 1
        fr = (
            await db_session.execute(
                text("SELECT flagged_reason FROM attendance WHERE id=:i"), {"i": att_id}
            )
        ).scalar()
        assert fr == "no_punch_out"
    finally:
        await _restore_sweep(db_session, parked)


async def test_no_punch_out_in_time_office_queue_and_disputable(client, db_session):
    w = await login(client, PHONES["w_att4"])
    to = await login(client, PHONES["time_mgr"])
    emp_id = await _me_id(client, w)
    await _clean_attendance(db_session, emp_id)
    today = now_ist().date()
    att_id = await _insert_open_punch(db_session, emp_id, today, flagged_reason="no_punch_out")

    # lands in the existing Time Office flagged queue, verification level preserved
    r = await client.get("/api/attendance/flagged", headers=to)
    assert r.status_code == 200
    rec = next((a for a in r.json() if a["id"] == att_id), None)
    assert rec is not None
    assert rec["flagged_reason"] == "no_punch_out"
    assert rec["verification_level"] == "verified"

    # the worker can dispute it ("this is wrong") even though the punch itself is verified
    r = await client.post(
        f"/api/attendance/{att_id}/regularize", json={"text_note": "I did punch out at the gate"}, headers=w
    )
    assert r.status_code == 200, r.text

    # Time Office resolves it → out of the queue
    r = await client.post(f"/api/attendance/{att_id}/approve", headers=to)
    assert r.status_code == 200
    r = await client.get("/api/attendance/flagged", headers=to)
    assert all(a["id"] != att_id for a in r.json())


async def test_late_punch_out_clears_no_punch_out_flag(client, db_session):
    w = await login(client, PHONES["w_att5"])
    emp_id = await _me_id(client, w)
    await _clean_attendance(db_session, emp_id)
    today = now_ist().date()
    att_id = await _insert_open_punch(db_session, emp_id, today, flagged_reason="no_punch_out")

    r = await client.post("/api/attendance/punch-out", headers=w)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == att_id
    assert body["punch_out_at"] is not None
    assert body["flagged_reason"] is None  # self-resolved — no Time Office noise


# =====================================================================
# 2. Shift-swap FOR UPDATE (real concurrency against live Postgres)
# =====================================================================

def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


async def _make_pending_manager_swap(client, db_session, swap_date: str) -> str:
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    r = await client.post(
        "/api/shift-swaps",
        json={"target_employee_id": target_id, "swap_date": swap_date, "reason": "race test"},
        headers=w1,
    )
    assert r.status_code == 200, r.text
    swap_id = r.json()["id"]
    r = await client.post(f"/api/shift-swaps/{swap_id}/respond", json={"accept": True}, headers=w2)
    assert r.status_code == 200
    return swap_id


async def test_swap_concurrent_decide_applies_exactly_once(client, db_session):
    swap_date = _d(25)  # far from other swap tests' dates
    swap_id = await _make_pending_manager_swap(client, db_session, swap_date)
    mgr = await login(client, PHONES["prod_mgr"])

    r1, r2 = await asyncio.gather(
        client.post(f"/api/shift-swaps/{swap_id}/decide", json={"approve": True}, headers=mgr),
        client.post(f"/api/shift-swaps/{swap_id}/decide", json={"approve": True}, headers=mgr),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)

    # the swap applied exactly ONCE: one assignment per employee, two audit rows (not four)
    n_assign = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM shift_assignments WHERE effective_date=:d AND source='swap'"),
            {"d": date.fromisoformat(swap_date)},
        )
    ).scalar()
    assert n_assign == 2
    n_audit = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='shift_swap.applied' "
                 "AND detail_json->>'swap_id'=:s"), {"s": swap_id},
        )
    ).scalar()
    assert n_audit == 2


async def test_swap_concurrent_respond_single_transition(client, db_session):
    swap_date = _d(26)
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    r = await client.post(
        "/api/shift-swaps",
        json={"target_employee_id": target_id, "swap_date": swap_date, "reason": "race test 2"},
        headers=w1,
    )
    assert r.status_code == 200, r.text
    swap_id = r.json()["id"]

    r1, r2 = await asyncio.gather(
        client.post(f"/api/shift-swaps/{swap_id}/respond", json={"accept": True}, headers=w2),
        client.post(f"/api/shift-swaps/{swap_id}/respond", json={"accept": True}, headers=w2),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
    status = (
        await db_session.execute(
            text("SELECT status FROM shift_swap_requests WHERE id=:i"), {"i": swap_id}
        )
    ).scalar()
    assert status == "pending_manager"


# =====================================================================
# 3. Offline outbox idempotency (client_uuid)
# =====================================================================

async def test_incident_client_uuid_replay_returns_same_row(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    cu = f"test-inc-{uuid_mod.uuid4()}"
    payload = {
        "category": "other", "department_code": "PRODUCTION", "photo_key": "p.jpg",
        "gps_lat": 19.0, "gps_lng": 74.7, "description": "leaking valve", "client_uuid": cu,
    }
    r1 = await client.post("/api/incidents", json=payload, headers=w)
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/incidents", json=payload, headers=w)  # outbox replay
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]
    n = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM incidents WHERE client_uuid=:c"), {"c": cu}
        )
    ).scalar()
    assert n == 1

    # regression: WITHOUT client_uuid two posts still create two incidents
    del payload["client_uuid"]
    ra = await client.post("/api/incidents", json=payload, headers=w)
    rb = await client.post("/api/incidents", json=payload, headers=w)
    assert ra.json()["id"] != rb.json()["id"]


async def test_form_submit_client_uuid_replay_returns_same_row(client, db_session):
    # ENGINEERING form + w_eng: keeps w_prod3's PRODUCTION last-mine pristine for test_p1_batch
    w = await login(client, PHONES["w_eng"])
    def_id = (
        await db_session.execute(
            text("SELECT id::text FROM form_definitions WHERE department_code='ENGINEERING' AND is_active LIMIT 1")
        )
    ).scalar_one()
    cu = f"test-form-{uuid_mod.uuid4()}"
    body = {"data_json": {"asset_name": "pump-2", "priority": "normal"}, "photos": [], "client_uuid": cu}
    r1 = await client.post(f"/api/forms/{def_id}/submit", json=body, headers=w)
    assert r1.status_code == 200, r1.text
    r2 = await client.post(f"/api/forms/{def_id}/submit", json=body, headers=w)
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]
    n = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM form_submissions WHERE client_uuid=:c"), {"c": cu}
        )
    ).scalar()
    assert n == 1
