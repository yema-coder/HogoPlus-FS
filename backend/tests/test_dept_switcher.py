"""CGM/MD department switcher (mobile "My Department" tab) — role scoping.

Rank <= 2 (CGM/MD) may browse ANY department's forms/submissions and submit on
behalf of the selected department (submission stamped with that department_code).
Manager (rank 3) and below are locked to their own department: any parameter
tampering returns 403.
"""

from tests.conftest import PHONES, login


async def _form_id(client, headers, dept: str, code: str) -> str:
    r = await client.get(f"/api/forms?department_code={dept}", headers=headers)
    assert r.status_code == 200, r.text
    return next(f["id"] for f in r.json() if f["code"] == code)


async def test_cgm_lists_any_department_forms(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/forms?department_code=ENGINEERING", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert all(f["department_code"] == "ENGINEERING" for f in r.json())
    r = await client.get("/api/forms?department_code=PRODUCTION", headers=headers)
    assert r.status_code == 200
    assert all(f["department_code"] == "PRODUCTION" for f in r.json())


async def test_cgm_cross_dept_submission_stamped_with_selected_dept(client):
    headers = await login(client, PHONES["cgm"])
    form_id = await _form_id(client, headers, "PRODUCTION", "hourly_process_log")
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 55.2}, "photos": ["p1.jpg"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["department_code"] == "PRODUCTION"


async def test_worker_cannot_submit_other_dept_form(client):
    cgm = await login(client, PHONES["cgm"])
    form_id = await _form_id(client, cgm, "PRODUCTION", "hourly_process_log")
    w = await login(client, PHONES["w_eng"])  # ENGINEERING worker
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 55.2}, "photos": []},
        headers=w,
    )
    assert r.status_code == 403


async def test_manager_cannot_submit_other_dept_form(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/forms?department_code=ENGINEERING", headers=cgm)
    form_id = r.json()[0]["id"]
    mgr = await login(client, PHONES["prod_mgr"])  # PRODUCTION manager
    r = await client.post(
        f"/api/forms/{form_id}/submit", json={"data_json": {}, "photos": []}, headers=mgr
    )
    assert r.status_code == 403


async def test_manager_can_still_submit_own_dept_form(client):
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/forms", headers=mgr)
    form_id = next(f["id"] for f in r.json() if f["code"] == "hourly_process_log")
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 51.0}, "photos": ["p1.jpg"]},
        headers=mgr,
    )
    assert r.status_code == 200, r.text
    assert r.json()["department_code"] == "PRODUCTION"


async def test_cgm_submissions_filter_by_department(client):
    headers = await login(client, PHONES["cgm"])
    # ensure at least one PRODUCTION submission exists
    form_id = await _form_id(client, headers, "PRODUCTION", "hourly_process_log")
    r = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "pan", "brix_value": 60.0}, "photos": ["p1.jpg"]},
        headers=headers,
    )
    assert r.status_code == 200

    r = await client.get("/api/submissions?department_code=PRODUCTION", headers=headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert all(s["department_code"] == "PRODUCTION" for s in items)

    r = await client.get("/api/submissions?department_code=ENGINEERING", headers=headers)
    assert r.status_code == 200
    assert all(s["department_code"] == "ENGINEERING" for s in r.json()["items"])
