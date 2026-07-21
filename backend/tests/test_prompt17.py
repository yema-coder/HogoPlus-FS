"""Prompt 17: direct-add + access guardrails, manual escalation, announcements,
face enrollment, push token registration."""
import pytest
from sqlalchemy import text

from app.notify import dispatcher
from tests.conftest import PHONES, employee_id_by_phone, login


async def _notif_types(client, headers) -> list[str]:
    r = await client.get("/api/notifications/mine", headers=headers)
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if isinstance(data, dict) else data
    return [n["type"] for n in items]


# ---------------- Part B: direct-add + edit guardrails ----------------

async def test_direct_add_by_time_office(client):
    to = await login(client, PHONES["time_mgr"])
    r = await client.post(
        "/api/admin/employees",
        json={
            "full_name": "New Direct Worker",
            "phone": "+919555555501",
            "department_code": "PRODUCTION",
            "role_code": "Worker",
            "shift_code": "A",
            "emp_id": "7001",
        },
        headers=to,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["onboarding_status"] == "approved"
    assert body["is_active"] is True
    assert body["role_code"] == "Worker"

    # duplicate phone / emp_id → 409
    for dup in (
        {"phone": "+919555555501", "emp_id": "7002"},
        {"phone": "+919555555502", "emp_id": "7001"},
    ):
        r = await client.post(
            "/api/admin/employees",
            json={
                "full_name": "Dup Attempt",
                "department_code": "PRODUCTION",
                "role_code": "Worker",
                **dup,
            },
            headers=to,
        )
        assert r.status_code == 409, r.text


async def test_direct_add_role_guardrails(client):
    to = await login(client, PHONES["time_mgr"])
    cgm = await login(client, PHONES["cgm"])
    worker = await login(client, PHONES["w_prod1"])

    payload = {
        "full_name": "Wannabe Manager",
        "phone": "+919555555503",
        "department_code": "ENGINEERING",
        "role_code": "Manager",
        "emp_id": "7003",
    }
    # Time Office may NOT create Manager+ accounts
    r = await client.post("/api/admin/employees", json=payload, headers=to)
    assert r.status_code == 403
    # CGM may
    r = await client.post("/api/admin/employees", json=payload, headers=cgm)
    assert r.status_code == 200, r.text
    # workers can't direct-add at all
    r = await client.post(
        "/api/admin/employees",
        json={**payload, "phone": "+919555555504", "emp_id": "7004"},
        headers=worker,
    )
    assert r.status_code == 403


async def test_patch_employee_guardrails(client, db_session):
    to = await login(client, PHONES["time_mgr"])
    cgm = await login(client, PHONES["cgm"])
    mgr_id = await employee_id_by_phone(db_session, PHONES["prod_mgr"])
    worker_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])

    # Time Office cannot touch Manager+ accounts
    r = await client.patch(f"/api/admin/employees/{mgr_id}", json={"full_name": "Hax"}, headers=to)
    assert r.status_code == 403
    # ...or grant Manager+ roles
    r = await client.patch(f"/api/admin/employees/{worker_id}", json={"role_code": "Manager"}, headers=to)
    assert r.status_code == 403
    # but CAN edit worker basics
    r = await client.patch(f"/api/admin/employees/{worker_id}", json={"full_name": "Renamed Worker"}, headers=to)
    assert r.status_code == 200
    assert r.json()["full_name"] == "Renamed Worker"
    # CGM can edit a manager
    r = await client.patch(f"/api/admin/employees/{mgr_id}", json={"full_name": "Prod Manager X"}, headers=cgm)
    assert r.status_code == 200


async def test_role_change_propagates_without_relogin(client, db_session):
    worker = await login(client, PHONES["w_prod2"])
    to = await login(client, PHONES["time_mgr"])
    worker_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])

    r = await client.patch(f"/api/admin/employees/{worker_id}", json={"role_code": "Staff"}, headers=to)
    assert r.status_code == 200
    # SAME token, no re-login: role is read from the DB per request
    r = await client.get("/api/auth/me", headers=worker)
    assert r.status_code == 200
    assert r.json()["role_code"] == "Staff"


async def test_employee_search_time_office_allowed(client):
    to = await login(client, PHONES["time_mgr"])
    worker = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/admin/employees?search=Prod", headers=to)
    assert r.status_code == 200
    assert len(r.json()) > 0
    r = await client.get("/api/admin/employees?search=Prod", headers=worker)
    assert r.status_code == 403


# ---------------- Part E: manual escalation ----------------

async def _create_incident(client, headers) -> str:
    r = await client.post(
        "/api/incidents",
        json={"category": "safety", "department_code": "PRODUCTION", "photo_key": "test.jpg"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_escalate_department_and_employee(client, db_session):
    worker = await login(client, PHONES["w_prod1"])
    mgr = await login(client, PHONES["prod_mgr"])
    cgm = await login(client, PHONES["cgm"])
    incident_id = await _create_incident(client, worker)

    # worker cannot escalate
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "department", "department_code": "ENGINEERING", "reason": "nope"},
        headers=worker,
    )
    assert r.status_code == 403

    # missing department_code → 422
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "department", "reason": "missing dept"},
        headers=mgr,
    )
    assert r.status_code == 422

    # dept without a manager (ENGINEERING) → CGM fallback
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "department", "department_code": "ENGINEERING", "reason": "needs eng review"},
        headers=mgr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "escalated"
    cgm_id = await employee_id_by_phone(db_session, PHONES["cgm"])
    assert body["escalated_to"] == cgm_id
    assert "incident_escalated" in await _notif_types(client, cgm)

    # re-escalate to a specific person
    to_id = await employee_id_by_phone(db_session, PHONES["time_mgr"])
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "employee", "employee_id": to_id, "reason": "time office please"},
        headers=mgr,
    )
    assert r.status_code == 200, r.text
    assert r.json()["escalated_to"] == to_id

    # escalating to a Worker target is rejected
    w_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "employee", "employee_id": w_id, "reason": "not a manager"},
        headers=mgr,
    )
    assert r.status_code == 422

    # resolved incidents cannot be escalated
    r = await client.post(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "note": "done", "resolution_photo_key": "fix.jpg"},
        headers=cgm,
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/incidents/{incident_id}/escalate",
        json={"mode": "department", "department_code": "ENGINEERING", "reason": "too late"},
        headers=mgr,
    )
    assert r.status_code == 409


async def test_escalation_targets(client, db_session):
    mgr = await login(client, PHONES["prod_mgr"])
    worker = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/incidents/escalation-targets", headers=mgr)
    assert r.status_code == 200
    ids = {e["id"] for e in r.json()}
    assert await employee_id_by_phone(db_session, PHONES["cgm"]) in ids
    assert await employee_id_by_phone(db_session, PHONES["time_mgr"]) in ids
    assert await employee_id_by_phone(db_session, PHONES["prod_mgr"]) not in ids  # excludes self
    assert all(e["role_rank"] <= 3 for e in r.json())
    r = await client.get("/api/incidents/escalation-targets", headers=worker)
    assert r.status_code == 403


# ---------------- Part F: announcements ----------------

async def test_announcement_scoping(client):
    mgr = await login(client, PHONES["prod_mgr"])
    cgm = await login(client, PHONES["cgm"])
    worker = await login(client, PHONES["w_prod1"])
    eng = await login(client, PHONES["w_eng"])

    # manager → own department OK
    r = await client.post(
        "/api/admin/announcements",
        json={"title": "Line 2 stop", "message": "Cleaning at 3pm", "audience": "department",
              "department_code": "PRODUCTION"},
        headers=mgr,
    )
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] > 0
    assert "announcement" in await _notif_types(client, worker)
    assert "announcement" not in await _notif_types(client, eng)

    # manager → other department / everyone → 403
    r = await client.post(
        "/api/admin/announcements",
        json={"title": "xx", "message": "yy", "audience": "department", "department_code": "ENGINEERING"},
        headers=mgr,
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/admin/announcements",
        json={"title": "xx", "message": "yy", "audience": "all"},
        headers=mgr,
    )
    assert r.status_code == 403

    # worker → 403
    r = await client.post(
        "/api/admin/announcements",
        json={"title": "xx", "message": "yy", "audience": "department", "department_code": "PRODUCTION"},
        headers=worker,
    )
    assert r.status_code == 403

    # CGM → everyone
    r = await client.post(
        "/api/admin/announcements",
        json={"title": "All hands", "message": "Meet at 10", "audience": "all"},
        headers=cgm,
    )
    assert r.status_code == 200
    assert r.json()["recipients"] > 0
    assert "announcement" in await _notif_types(client, eng)


async def test_announcement_push_mirrors_token(client, monkeypatch):
    """The push mirror fires with the recipient's stored Expo token."""
    calls: list[tuple[str | None, str]] = []

    class Recorder:
        async def push(self, token, title, body, data=None):
            calls.append((token, title))

    monkeypatch.setattr(dispatcher, "push_sender", Recorder())

    worker = await login(client, PHONES["w_prod1"])
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.patch(
        "/api/employees/me",
        json={"expo_push_token": "ExponentPushToken[test-abc-123]"},
        headers=worker,
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/admin/announcements",
        json={"title": "Push check", "message": "hello", "audience": "department",
              "department_code": "PRODUCTION"},
        headers=mgr,
    )
    assert r.status_code == 200
    tokens = [c[0] for c in calls]
    assert "ExponentPushToken[test-abc-123]" in tokens
    assert any("Push check" in c[1] for c in calls)


# ---------------- Part C: face enrollment ----------------

async def test_face_enroll_flow(client, db_session):
    worker = await login(client, PHONES["w_prod3"])
    to = await login(client, PHONES["time_mgr"])

    # other suites may have bootstrapped a reference for this worker — start clean
    await db_session.execute(
        text("UPDATE employees SET reference_selfie_key=NULL, reference_selfie_set_at=NULL WHERE phone=:p"),
        {"p": PHONES["w_prod3"]},
    )
    await db_session.commit()

    r = await client.get("/api/auth/me", headers=worker)
    assert r.json()["has_face_reference"] is False

    r = await client.post(
        "/api/employees/me/face-enroll", json={"selfie_key": "enroll-1.jpg"}, headers=worker
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_face_reference"] is True

    # second enrollment blocked — the existing reset endpoint is the review path
    r = await client.post(
        "/api/employees/me/face-enroll", json={"selfie_key": "enroll-2.jpg"}, headers=worker
    )
    assert r.status_code == 409

    # supervised review: Time Office manager was informed
    assert "face_enrolled" in await _notif_types(client, to)

    # audit trail uses the enrollment-specific event
    row = (
        await db_session.execute(
            text("SELECT count(*) FROM audit_events WHERE action='employee.reference_selfie_from_enrollment'")
        )
    ).scalar()
    assert row == 1

    # reset (reject path) clears it → enrollment possible again
    worker_id = await employee_id_by_phone(db_session, PHONES["w_prod3"])
    r = await client.post(f"/api/admin/employees/{worker_id}/reset-reference-selfie", headers=to)
    assert r.status_code == 200
    r = await client.get("/api/auth/me", headers=worker)
    assert r.json()["has_face_reference"] is False
