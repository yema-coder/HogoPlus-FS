from sqlalchemy import text

from tests.conftest import PHONES, login


async def _prod_form_id(client, headers) -> str:
    r = await client.get("/api/forms", headers=headers)
    assert r.status_code == 200
    return next(f["id"] for f in r.json() if f["code"] == "hourly_process_log")


async def _submit_valid(client, headers) -> dict:
    form_id = await _prod_form_id(client, headers)
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 55.2}, "photos": ["p1.jpg"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_worker_sees_only_own_dept_forms(client):
    headers = await login(client, PHONES["w_eng"])
    r = await client.get("/api/forms", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert all(f["department_code"] == "ENGINEERING" for f in r.json())
    # explicit request for another department is still scoped to own dept
    r = await client.get("/api/forms?department_code=PRODUCTION", headers=headers)
    assert all(f["department_code"] == "ENGINEERING" for f in r.json())


async def test_manager_can_view_other_dept_forms(client):
    headers = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/forms?department_code=ENGINEERING", headers=headers)
    assert r.status_code == 200
    assert any(f["code"] == "job_card" for f in r.json())


async def test_submit_valid_form(client):
    headers = await login(client, PHONES["w_prod1"])
    sub = await _submit_valid(client, headers)
    assert sub["status"] == "submitted"
    assert sub["form_version"] == 1


async def test_submit_missing_required_field(client):
    headers = await login(client, PHONES["w_prod1"])
    form_id = await _prod_form_id(client, headers)
    r = await client.post(f"/api/forms/{form_id}/submit", json={"data_json": {"brix_value": 50}}, headers=headers)
    assert r.status_code == 400
    assert any("station" in e for e in r.json()["detail"]["errors"])


async def test_submit_invalid_select_option(client):
    headers = await login(client, PHONES["w_prod1"])
    form_id = await _prod_form_id(client, headers)
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "bogus", "brix_value": 50}},
        headers=headers,
    )
    assert r.status_code == 400
    assert any("station" in e for e in r.json()["detail"]["errors"])


async def test_submit_number_out_of_range(client):
    headers = await login(client, PHONES["w_prod1"])
    form_id = await _prod_form_id(client, headers)
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 150}},
        headers=headers,
    )
    assert r.status_code == 400
    assert any("brix_value" in e for e in r.json()["detail"]["errors"])


async def test_manager_approves_submission(client, db_session):
    w_headers = await login(client, PHONES["w_prod1"])
    sub = await _submit_valid(client, w_headers)
    m_headers = await login(client, PHONES["prod_mgr"])
    r = await client.post(f"/api/submissions/{sub['id']}/approve", headers=m_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    audit = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='form_submission.approved' AND entity_id=:e"),
            {"e": sub["id"]},
        )
    ).scalar()
    assert audit == 1


async def test_manager_rejects_with_reason(client):
    w_headers = await login(client, PHONES["w_prod1"])
    sub = await _submit_valid(client, w_headers)
    m_headers = await login(client, PHONES["prod_mgr"])
    r = await client.post(
        f"/api/submissions/{sub['id']}/reject", json={"reason": "blurry photo"}, headers=m_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "blurry photo"


async def test_worker_cannot_approve(client):
    w_headers = await login(client, PHONES["w_prod1"])
    sub = await _submit_valid(client, w_headers)
    other = await login(client, PHONES["w_prod2"])
    r = await client.post(f"/api/submissions/{sub['id']}/approve", headers=other)
    assert r.status_code == 403


async def test_submissions_list_scoped_to_worker(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/submissions", headers=headers)
    assert r.status_code == 200
    me = await client.get("/api/auth/me", headers=headers)
    my_id = me.json()["id"]
    assert all(item["submitted_by"] == my_id for item in r.json()["items"])
    # a worker from another dept sees none of these
    eng_headers = await login(client, PHONES["w_eng"])
    r2 = await client.get("/api/submissions", headers=eng_headers)
    assert all(item["department_code"] != "PRODUCTION" for item in r2.json()["items"])


async def test_manager_sees_department_submissions(client):
    headers = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/submissions", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all(item["department_code"] == "PRODUCTION" for item in r.json()["items"])
