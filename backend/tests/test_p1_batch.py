"""v1.0.21 P1 batch tests (live local Postgres + Redis):

1. "My Month" — GET /attendance/month-summary: single source of truth (worker
   card and TO flagged queue MUST agree), previous-month comparison, role
   boundaries (worker cannot read others; TO/CGM can).
2. Attendance regularization — one open request per punch (DB-enforced),
   evidence attached in the TO queue, approve/reject parity with the standalone
   flag endpoints, audit with reviewer name, worker notification, boundaries.
3. Duplicate incident clustering — rules-based (same zone + category within a
   TUNABLE window), display-only (both records intact), one-tap audited unlink,
   settings tuning without deploy.
4. Same-as-last — /vehicles/last-mine (plate returned for explicit confirm
   only) and /forms/{id}/last-mine.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app import ai_core
from tests.conftest import PHONES, login

pytestmark = pytest.mark.asyncio

IST = timezone(timedelta(hours=5, minutes=30))


async def _me(client, headers) -> dict:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    return r.json()


async def _mk_attendance(db_session, employee_id: str, day, flagged=True, approved_by=None):
    from app.models import Attendance

    row = Attendance(
        employee_id=uuid.UUID(employee_id),
        date=day,
        punch_in_at=datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=8),
        selfie_key="selfie.jpg",
        verification_level="flagged" if flagged else "verified",
        flagged_reason="face_mismatch" if flagged else None,
        approved_by=uuid.UUID(approved_by) if approved_by else None,
        is_late=False,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


# =====================================================================
# 1. My Month — shared source of truth
# =====================================================================

async def test_month_summary_counts_and_prev_month(client, db_session):
    w = await login(client, PHONES["w_att1"])
    me = await _me(client, w)
    today = datetime.now(IST).date()
    first = today.replace(day=1)
    # other suites also punch for w_att1 — assert DELTAS against a baseline
    base = (await client.get("/api/attendance/month-summary", headers=w)).json()
    await _mk_attendance(db_session, me["id"], first.replace(day=24), flagged=True)
    await _mk_attendance(db_session, me["id"], first.replace(day=25), flagged=False)
    prev_day = (first - timedelta(days=1)).replace(day=24)
    await _mk_attendance(db_session, me["id"], prev_day, flagged=False)

    r = await client.get("/api/attendance/month-summary", headers=w)
    assert r.status_code == 200, r.text
    body = r.json()
    cur, prev = body["current"], body["previous"]
    assert cur["days_present"] == base["current"]["days_present"] + 2
    assert cur["days_flagged_pending"] == base["current"]["days_flagged_pending"] + 1
    assert prev["days_present"] == base["previous"]["days_present"] + 1
    assert prev["month"] == prev_day.strftime("%Y-%m")


async def test_month_summary_matches_to_flagged_queue(client, db_session):
    """THE anti-dispute guarantee: the worker's flagged count and the TO's
    flagged queue use the same filter — counts must be identical."""
    w = await login(client, PHONES["w_att2"])
    to = await login(client, PHONES["time_mgr"])
    me = await _me(client, w)
    day = datetime.now(IST).date().replace(day=26)
    await _mk_attendance(db_session, me["id"], day, flagged=True)

    month = day.strftime("%Y-%m")
    summary = (
        await client.get(f"/api/attendance/month-summary?month={month}", headers=w)
    ).json()
    flagged_queue = (await client.get("/api/attendance/flagged", headers=to)).json()
    queue_count_for_worker_month = sum(
        1
        for f in flagged_queue
        if f["employee_id"] == me["id"] and f["date"].startswith(month)
    )
    assert summary["current"]["days_flagged_pending"] == queue_count_for_worker_month
    assert queue_count_for_worker_month >= 1


async def test_month_summary_role_boundaries(client, db_session):
    w1 = await login(client, PHONES["w_att1"])
    w2 = await login(client, PHONES["w_att2"])
    to = await login(client, PHONES["time_mgr"])
    other = await _me(client, w2)
    # a worker may NOT read another worker's month
    r = await client.get(
        f"/api/attendance/month-summary?employee_id={other['id']}", headers=w1
    )
    assert r.status_code == 403
    # the Time Office may
    r = await client.get(
        f"/api/attendance/month-summary?employee_id={other['id']}", headers=to
    )
    assert r.status_code == 200
    assert r.json()["employee_id"] == other["id"]
    # bad month format
    r = await client.get("/api/attendance/month-summary?month=junk", headers=w1)
    assert r.status_code == 400


# =====================================================================
# 2. Regularization
# =====================================================================

async def test_regularize_full_lifecycle_approve(client, db_session):
    w = await login(client, PHONES["w_att3"])
    to = await login(client, PHONES["time_mgr"])
    me = await _me(client, w)
    day = datetime.now(IST).date().replace(day=27)
    att = await _mk_attendance(db_session, me["id"], day, flagged=True)
    month = day.strftime("%Y-%m")
    base = (
        await client.get(f"/api/attendance/month-summary?month={month}", headers=w)
    ).json()["current"]

    # worker raises a dispute with voice note + text
    r = await client.post(
        f"/api/attendance/{att.id}/regularize",
        json={"text_note": "मी हजर होतो", "voice_note_key": "reg-vn.m4a"},
        headers=w,
    )
    assert r.status_code == 200, r.text
    reg_id = r.json()["id"]

    # ONE open request per punch — second attempt blocked with trilingual detail
    r2 = await client.post(f"/api/attendance/{att.id}/regularize", json={}, headers=w)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "reg_already_open"

    # worker sees the request status
    mine = (await client.get("/api/attendance/regularizations/mine", headers=w)).json()
    assert any(m["id"] == reg_id and m["status"] == "open" for m in mine)

    # attendance/mine rows carry the regularization status
    rows = (await client.get(f"/api/attendance/mine?month={month}", headers=w)).json()
    row = next(x for x in rows if x["id"] == str(att.id))
    assert row["regularization"]["status"] == "open"

    # TO queue shows the original punch evidence alongside
    queue = (await client.get("/api/attendance/regularizations", headers=to)).json()
    item = next(q for q in queue if q["id"] == reg_id)
    assert item["employee_name"] and item["emp_id"]
    assert item["text_note"] == "मी हजर होतो"
    assert item["voice_note_url"] == "/api/files/reg-vn.m4a"
    ev = item["attendance"]
    assert ev["flagged_reason"] == "face_mismatch"
    assert ev["selfie_url"]  # original selfie
    assert ev["verification_level"] == "flagged"

    # TO approves — reg closed AND the punch resolved exactly like /approve
    r = await client.post(
        f"/api/attendance/regularizations/{reg_id}/decide",
        json={"action": "approve", "note": "verified on CCTV"},
        headers=to,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # punch resolved → disappears from the TO flagged queue
    flagged_queue = (await client.get("/api/attendance/flagged", headers=to)).json()
    assert not any(f["id"] == str(att.id) for f in flagged_queue)
    # …and the worker's My Month counts move accordingly (shared source of truth)
    summary = (
        await client.get(f"/api/attendance/month-summary?month={month}", headers=w)
    ).json()
    assert summary["current"]["days_flagged_pending"] == base["days_flagged_pending"] - 1
    assert summary["current"]["days_flagged_resolved"] == base["days_flagged_resolved"] + 1

    # audit trail carries the reviewer's name
    from app.models import AuditEvent

    audits = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_id == reg_id,
                AuditEvent.action == "attendance.regularization_approved",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].detail_json["reviewer_name"]

    # worker got notified
    notifs = (await client.get("/api/notifications/mine", headers=w)).json()
    items = notifs["items"] if isinstance(notifs, dict) else notifs
    assert any(n["type"] == "regularization_decided" for n in items)

    # deciding twice → 409
    r = await client.post(
        f"/api/attendance/regularizations/{reg_id}/decide",
        json={"action": "approve"}, headers=to,
    )
    assert r.status_code == 409


async def test_regularize_reject_resolves_punch(client, db_session):
    w = await login(client, PHONES["w_att4"])
    to = await login(client, PHONES["time_mgr"])
    me = await _me(client, w)
    att = await _mk_attendance(
        db_session, me["id"], datetime.now(IST).date().replace(day=4), flagged=True
    )
    reg_id = (
        await client.post(f"/api/attendance/{att.id}/regularize", json={}, headers=w)
    ).json()["id"]
    r = await client.post(
        f"/api/attendance/regularizations/{reg_id}/decide",
        json={"action": "reject", "note": "not on CCTV"}, headers=to,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    row = (
        await db_session.execute(
            text("SELECT approved_by, face_verified FROM attendance WHERE id = CAST(:id AS uuid)"),
            {"id": str(att.id)},
        )
    ).one()
    assert row.approved_by is not None  # resolved (as rejected) — same lifecycle
    assert row.face_verified is False  # parity with POST /attendance/{id}/reject
    mine = (await client.get("/api/attendance/regularizations/mine", headers=w)).json()
    assert any(m["id"] == reg_id and m["status"] == "rejected" and m["review_note"] == "not on CCTV" for m in mine)


async def test_regularize_boundaries(client, db_session):
    w = await login(client, PHONES["w_att5"])
    w_other = await login(client, PHONES["w_att1"])
    prod_mgr = await login(client, PHONES["prod_mgr"])
    me = await _me(client, w)
    day = datetime.now(IST).date().replace(day=5)
    att_ok = await _mk_attendance(db_session, me["id"], day, flagged=True)
    att_clean = await _mk_attendance(db_session, me["id"], day + timedelta(days=1), flagged=False)

    # cannot dispute someone else's punch
    r = await client.post(f"/api/attendance/{att_ok.id}/regularize", json={}, headers=w_other)
    assert r.status_code == 404
    # cannot dispute a non-flagged punch
    r = await client.post(f"/api/attendance/{att_clean.id}/regularize", json={}, headers=w)
    assert r.status_code == 409
    # workers cannot read the TO queue; non-TO managers cannot either
    assert (await client.get("/api/attendance/regularizations", headers=w)).status_code == 403
    assert (await client.get("/api/attendance/regularizations", headers=prod_mgr)).status_code == 403
    # workers cannot decide
    reg_id = (
        await client.post(f"/api/attendance/{att_ok.id}/regularize", json={}, headers=w)
    ).json()["id"]
    r = await client.post(
        f"/api/attendance/regularizations/{reg_id}/decide",
        json={"action": "approve"}, headers=w,
    )
    assert r.status_code == 403
    # unauthenticated
    assert (await client.get("/api/attendance/regularizations/mine")).status_code == 401


# =====================================================================
# 3. Duplicate incident clustering
# =====================================================================

def _patch_classify(monkeypatch, category="machine_breakdown"):
    async def fake_text_json(system, prompt):
        return {
            "category": category, "department_code": "PRODUCTION",
            "severity": "normal", "confidence": 0.8,
            "reason": "test", "reason_mr": "चाचणी",
        }

    class FakeStorage:
        def get(self, key):
            raise FileNotFoundError(key)  # photo unavailable → text classification

        def url_for(self, key):
            return f"/api/files/{key}"

    monkeypatch.setattr(ai_core, "text_json", fake_text_json)
    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())


async def _mk_incident(client, headers, db_session, zone="GATE-1", created_shift_min=0):
    r = await client.post(
        "/api/incidents",
        json={
            "category": "other", "department_code": "PRODUCTION",
            "photo_key": "p.jpg", "description": "test dup",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    inc_id = r.json()["id"]
    stmt = "UPDATE incidents SET ble_zone = :z"
    params = {"z": zone, "id": inc_id}
    if created_shift_min:
        stmt += ", created_at = created_at - make_interval(mins => :m)"
        params["m"] = created_shift_min
    await db_session.execute(text(stmt + " WHERE id = CAST(:id AS uuid)"), params)
    await db_session.commit()
    return inc_id


async def test_duplicates_cluster_same_zone_category_within_window(
    client, db_session, monkeypatch
):
    from app.tasks import _classify_incident_async

    _patch_classify(monkeypatch)
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])

    a = await _mk_incident(client, w1, db_session, zone="Z-BOILER", created_shift_min=10)
    b = await _mk_incident(client, w2, db_session, zone="Z-BOILER")
    c = await _mk_incident(client, w2, db_session, zone="Z-GATE")  # different zone

    await _classify_incident_async(a)
    await _classify_incident_async(b)
    await _classify_incident_async(c)

    det_b = (await client.get(f"/api/incidents/{b}", headers=w2)).json()
    det_c = (await client.get(f"/api/incidents/{c}", headers=w2)).json()
    assert det_b["duplicate_of"] == a, "same zone+category within window → clustered"
    assert det_c["duplicate_of"] is None, "different zone → NOT clustered"

    # DISPLAY-ONLY: both records fully intact — own reporter, status, description
    det_a = (await client.get(f"/api/incidents/{a}", headers=w1)).json()
    assert det_a["duplicate_of"] is None  # root stays a root
    assert det_a["reported_by"] != det_b["reported_by"]
    assert det_b["status"] == det_a["status"] == "submitted"
    assert det_b["description"] == "test dup"

    # manager list shows reporter_name so the card can say "2 reports: …"
    mgr = await login(client, PHONES["prod_mgr"])
    lst = (await client.get("/api/incidents", headers=mgr)).json()
    got_b = next(i for i in lst if i["id"] == b)
    assert got_b["reporter_name"]
    assert got_b["duplicate_of"] == a


async def test_duplicates_window_tunable_without_deploy(client, db_session, monkeypatch):
    from app.tasks import _classify_incident_async

    _patch_classify(monkeypatch)
    cgm = await login(client, PHONES["cgm"])
    w1 = await login(client, PHONES["w_prod1"])

    # shrink the window to 5 minutes via settings — no deploy
    r = await client.patch("/api/admin/settings", json={"dup_window_minutes": 5}, headers=cgm)
    assert r.status_code == 200, r.text
    try:
        old = await _mk_incident(client, w1, db_session, zone="Z-MILL", created_shift_min=20)
        new = await _mk_incident(client, w1, db_session, zone="Z-MILL")
        await _classify_incident_async(old)
        await _classify_incident_async(new)
        det = (await client.get(f"/api/incidents/{new}", headers=w1)).json()
        assert det["duplicate_of"] is None, "outside the tuned 5-min window → NOT clustered"
        # settings endpoint exposes the knobs
        s = (await client.get("/api/admin/settings", headers=cgm)).json()
        assert s["dup_window_minutes"] == 5
        assert s["dup_same_zone"] is True and s["dup_same_category"] is True
    finally:
        await client.patch("/api/admin/settings", json={"dup_window_minutes": 30}, headers=cgm)


async def test_duplicates_different_category_not_clustered(client, db_session, monkeypatch):
    from app.tasks import _classify_incident_async

    w1 = await login(client, PHONES["w_prod1"])
    a = await _mk_incident(client, w1, db_session, zone="Z-KILN", created_shift_min=5)
    b = await _mk_incident(client, w1, db_session, zone="Z-KILN")
    _patch_classify(monkeypatch, category="fire")
    await _classify_incident_async(a)
    _patch_classify(monkeypatch, category="electrical")
    await _classify_incident_async(b)
    det = (await client.get(f"/api/incidents/{b}", headers=w1)).json()
    assert det["duplicate_of"] is None


async def test_unlink_duplicate_one_tap_audited(client, db_session, monkeypatch):
    from app.models import AuditEvent, IncidentTimeline
    from app.tasks import _classify_incident_async

    _patch_classify(monkeypatch)
    w1 = await login(client, PHONES["w_prod1"])
    mgr = await login(client, PHONES["prod_mgr"])
    to_mgr = await login(client, PHONES["time_mgr"])

    a = await _mk_incident(client, w1, db_session, zone="Z-PAN", created_shift_min=3)
    b = await _mk_incident(client, w1, db_session, zone="Z-PAN")
    await _classify_incident_async(a)
    await _classify_incident_async(b)
    assert (await client.get(f"/api/incidents/{b}", headers=w1)).json()["duplicate_of"] == a

    # boundaries: worker cannot unlink; a manager of ANOTHER dept cannot either
    assert (await client.post(f"/api/incidents/{b}/unlink-duplicate", headers=w1)).status_code == 403
    assert (await client.post(f"/api/incidents/{b}/unlink-duplicate", headers=to_mgr)).status_code == 403

    # the department manager unlinks in one tap
    r = await client.post(f"/api/incidents/{b}/unlink-duplicate", headers=mgr)
    assert r.status_code == 200
    assert r.json()["duplicate_of"] is None
    # unlinking twice → 409
    assert (await client.post(f"/api/incidents/{b}/unlink-duplicate", headers=mgr)).status_code == 409

    # audited + timelined
    audits = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "incident.duplicate_unlinked",
                AuditEvent.entity_id == b,
            )
        )
    ).scalars().all()
    assert len(audits) == 1 and audits[0].detail_json["reviewer_name"]
    tl = (
        await db_session.execute(
            select(IncidentTimeline).where(
                IncidentTimeline.incident_id == uuid.UUID(b),
                IncidentTimeline.event.in_(("duplicate_linked", "duplicate_unlinked")),
            )
        )
    ).scalars().all()
    assert {t.event for t in tl} == {"duplicate_linked", "duplicate_unlinked"}


# =====================================================================
# 4. Same-as-last
# =====================================================================

async def test_vehicles_last_mine(client):
    cgm = await login(client, PHONES["cgm"])
    sec = await login(client, PHONES["w_sec"])
    other = await login(client, PHONES["w_prod3"])
    r = await client.patch(
        "/api/admin/settings", json={"vehicle_log_enabled": True}, headers=cgm
    )
    assert r.status_code == 200, r.text
    try:
        r = await client.post(
            "/api/vehicles/log",
            json={
                "plate": "MH12AB1234", "vehicle_type": "truck", "direction": "in",
                "driver_name": "Ravi", "purpose": "Cane delivery",
            },
            headers=sec,
        )
        assert r.status_code == 200, r.text
        last = (await client.get("/api/vehicles/last-mine", headers=sec)).json()["log"]
        assert last["plate"] == "MH12AB1234"
        assert last["vehicle_type"] == "truck"
        assert last["driver_name"] == "Ravi"
        assert last["purpose"] == "Cane delivery"
        # someone who never logged gets None — no cross-user leakage
        assert (await client.get("/api/vehicles/last-mine", headers=other)).json()["log"] is None
        assert (await client.get("/api/vehicles/last-mine")).status_code == 401
    finally:
        await client.patch(
            "/api/admin/settings", json={"vehicle_log_enabled": False}, headers=cgm
        )


async def test_forms_last_mine(client, db_session):
    w = await login(client, PHONES["w_prod3"])
    w2 = await login(client, PHONES["w_eng"])
    def_id = (
        await db_session.execute(
            text("SELECT id::text FROM form_definitions WHERE department_code='PRODUCTION' AND is_active LIMIT 1")
        )
    ).scalar_one()
    # nothing yet
    r = await client.get(f"/api/forms/{def_id}/last-mine", headers=w)
    assert r.status_code == 200 and r.json()["data_json"] is None
    # submit once
    r = await client.post(
        f"/api/forms/{def_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 42}, "photos": []},
        headers=w,
    )
    assert r.status_code == 200, r.text
    last = (await client.get(f"/api/forms/{def_id}/last-mine", headers=w)).json()
    assert last["data_json"]["brix_value"] == 42 and last["created_at"]
    # another user's last-mine is unaffected
    assert (await client.get(f"/api/forms/{def_id}/last-mine", headers=w2)).json()["data_json"] is None
