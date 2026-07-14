"""Phase 3 backend additions: swap candidates/cancel/enrichment, staff dept
submissions scope, submission detail, flagged attendance enrichment."""
from datetime import date, timedelta

from tests.conftest import PHONES, employee_id_by_phone, login


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


# ---------- swap candidates ----------

async def test_swap_candidates_worker(client):
    w1 = await login(client, PHONES["w_prod1"])
    r = await client.get(f"/api/shift-swaps/candidates?date={_d(6)}", headers=w1)
    assert r.status_code == 200, r.text
    data = r.json()
    my_shift = data["my_shift_code"]
    assert my_shift  # has a baseline shift
    # w_prod2 (B) differs; w_prod3 (A, same as requester) must be excluded
    assert len(data["candidates"]) >= 1
    assert all(c["shift_code"] != my_shift for c in data["candidates"])
    assert all(c["full_name"] and c["emp_id"] for c in data["candidates"])


async def test_swap_candidates_requires_eligibility(client):
    staff = await login(client, PHONES["staff_prod"])
    r = await client.get(f"/api/shift-swaps/candidates?date={_d(1)}", headers=staff)
    assert r.status_code == 403


async def test_swap_candidates_rejects_past_date(client):
    w1 = await login(client, PHONES["w_prod1"])
    r = await client.get(f"/api/shift-swaps/candidates?date={_d(-1)}", headers=w1)
    assert r.status_code == 400


# ---------- swap cancel + enrichment ----------

async def test_swap_cancel_and_enrichment(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])

    r = await client.post(
        "/api/shift-swaps",
        json={"target_employee_id": target_id, "swap_date": _d(3), "reason": "cancel test"},
        headers=w1,
    )
    assert r.status_code == 200, r.text
    swap = r.json()
    # enrichment present
    assert swap["requester_name"] and swap["target_name"]
    assert swap["requester_shift_code"] == "A"
    assert swap["target_shift_code"] == "B"
    assert swap["department_code"] == "PRODUCTION"

    # target cannot cancel
    r = await client.post(f"/api/shift-swaps/{swap['id']}/cancel", headers=w2)
    assert r.status_code == 403

    # requester cancels while pending_target
    r = await client.post(f"/api/shift-swaps/{swap['id']}/cancel", headers=w1)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # cannot cancel twice
    r = await client.post(f"/api/shift-swaps/{swap['id']}/cancel", headers=w1)
    assert r.status_code == 409

    # target can no longer respond
    r = await client.post(f"/api/shift-swaps/{swap['id']}/respond", json={"accept": True}, headers=w2)
    assert r.status_code == 409


# ---------- staff/clerk department submissions scope ----------

async def _submit_prod_form(client, headers, db_session):
    from sqlalchemy import text

    def_id = (
        await db_session.execute(
            text("SELECT id FROM form_definitions WHERE department_code='PRODUCTION' LIMIT 1")
        )
    ).scalar()
    r = await client.post(
        f"/api/forms/{def_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 42}, "photos": []},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_staff_department_scope(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    staff = await login(client, PHONES["staff_prod"])
    sub = await _submit_prod_form(client, w1, db_session)

    # default scope: staff sees only their own (not the worker's)
    r = await client.get("/api/submissions", headers=staff)
    assert all(s["id"] != sub["id"] for s in r.json()["items"])

    # department scope: staff sees the worker's submission read-only
    r = await client.get("/api/submissions?scope=department", headers=staff)
    assert any(s["id"] == sub["id"] for s in r.json()["items"])

    # staff still cannot approve
    r = await client.post(f"/api/submissions/{sub['id']}/approve", headers=staff)
    assert r.status_code == 403


async def test_worker_cannot_use_department_scope_to_see_others(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    sub = await _submit_prod_form(client, w1, db_session)
    r = await client.get("/api/submissions?scope=department", headers=w2)
    assert all(s["id"] != sub["id"] for s in r.json()["items"])


# ---------- submission detail ----------

async def test_submission_detail_scoping(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    staff = await login(client, PHONES["staff_prod"])
    w_eng = await login(client, PHONES["w_eng"])
    mgr = await login(client, PHONES["prod_mgr"])
    cgm = await login(client, PHONES["cgm"])
    sub = await _submit_prod_form(client, w1, db_session)

    for headers in (w1, staff, mgr, cgm):
        r = await client.get(f"/api/submissions/{sub['id']}", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["submitted_by_name"]

    # other-department worker: forbidden
    r = await client.get(f"/api/submissions/{sub['id']}", headers=w_eng)
    assert r.status_code == 403


# ---------- flagged attendance enrichment ----------

async def test_flagged_attendance_includes_employee_name(client):
    w = await login(client, PHONES["w_prod3"])
    r = await client.post(
        "/api/attendance/punch-in",
        json={"selfie_key": "selfie-flag-test.jpg", "gps_lat": None, "gps_lng": None},
        headers=w,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_level"] == "flagged"

    tm = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/attendance/flagged", headers=tm)
    assert r.status_code == 200
    rows = r.json()
    assert rows and all("employee_name" in x and "emp_id" in x and "department_code" in x for x in rows)
