import io

from sqlalchemy import text

from tests.conftest import PHONES, employee_id_by_phone, login


async def test_admin_settings_patch_cgm_only(client, db_session):
    cgm = await login(client, PHONES["cgm"])
    r = await client.patch("/api/admin/settings", json={"radius_meters": 650}, headers=cgm)
    assert r.status_code == 200
    assert r.json()["radius_meters"] == 650
    audit = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='settings.updated'")
        )
    ).scalar()
    assert audit >= 1
    # worker forbidden
    w = await login(client, PHONES["w_prod1"])
    r = await client.patch("/api/admin/settings", json={"radius_meters": 100}, headers=w)
    assert r.status_code == 403
    # restore
    r = await client.patch("/api/admin/settings", json={"radius_meters": 500}, headers=cgm)
    assert r.json()["radius_meters"] == 500


async def test_assign_manager(client, db_session):
    cgm = await login(client, PHONES["cgm"])
    eng_id = await employee_id_by_phone(db_session, PHONES["w_eng"])
    r = await client.post(
        "/api/admin/departments/GODOWN/assign-manager", json={"employee_id": eng_id}, headers=cgm
    )
    assert r.status_code == 200
    assert r.json()["manager_employee_id"] == eng_id
    # manager (rank 3) cannot assign
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.post(
        "/api/admin/departments/GODOWN/assign-manager", json={"employee_id": eng_id}, headers=mgr
    )
    assert r.status_code == 403


async def test_time_office_fixes_seeded_phone(client, db_session):
    tm = await login(client, PHONES["time_mgr"])
    emp_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE emp_id='0120'"))
    ).scalar()
    r = await client.patch(
        f"/api/admin/employees/{emp_id}", json={"phone": "+919777777701"}, headers=tm
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+919777777701"
    assert body["onboarding_status"] == "approved"  # seeded -> approved once phone fixed
    # that employee can now log in
    r = await client.post("/api/auth/verify-otp", json={"phone": "+919777777701", "otp": "123456"})
    assert r.status_code == 200 and r.json()["is_new"] is False
    # worker cannot patch employees
    w = await login(client, PHONES["w_prod1"])
    r = await client.patch(f"/api/admin/employees/{emp_id}", json={"full_name": "Hack"}, headers=w)
    assert r.status_code == 403


async def test_beacon_crud(client):
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.post(
        "/api/admin/beacons",
        json={"mac_address": "dd:ee:ff:00:11:22",
              "zone_label_en": "Mill Gate", "zone_label_hi": "मिल गेट", "zone_label_mr": "मिल गेट",
              "department_code": "SECURITY"},
        headers=mgr,
    )
    assert r.status_code == 200
    beacon = r.json()
    assert beacon["mac_address"] == "DD:EE:FF:00:11:22"  # normalized to uppercase
    # invalid MAC format rejected
    r = await client.post(
        "/api/admin/beacons",
        json={"mac_address": "not-a-mac", "zone_label_en": "X", "zone_label_hi": "X", "zone_label_mr": "X"},
        headers=mgr,
    )
    assert r.status_code == 422
    # duplicate MAC rejected
    r = await client.post(
        "/api/admin/beacons",
        json={"mac_address": "DD:EE:FF:00:11:22", "zone_label_en": "X", "zone_label_hi": "X", "zone_label_mr": "X"},
        headers=mgr,
    )
    assert r.status_code == 409
    r = await client.patch(
        f"/api/admin/beacons/{beacon['id']}", json={"is_active": False}, headers=mgr
    )
    assert r.json()["is_active"] is False
    r = await client.delete(f"/api/admin/beacons/{beacon['id']}", headers=mgr)
    assert r.json()["deleted"] is True


async def test_file_upload_requires_token(client):
    r = await client.post(
        "/api/files/upload", files={"file": ("selfie.png", io.BytesIO(b"\x89PNG\r\n\x1a\nxx"), "image/png")}
    )
    assert r.status_code == 401


async def test_file_upload_and_serve(client):
    headers = await login(client, PHONES["w_prod1"])
    content = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = await client.post(
        "/api/files/upload",
        files={"file": ("selfie.png", io.BytesIO(content), "image/png")},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key"].endswith(".png")
    r2 = await client.get(body["url"])
    assert r2.status_code == 200
    assert r2.content == content
    # bad extension rejected
    r3 = await client.post(
        "/api/files/upload",
        files={"file": ("evil.exe", io.BytesIO(b"xx"), "application/octet-stream")},
        headers=headers,
    )
    assert r3.status_code == 400
    # extension/content mismatch rejected (magic bytes check)
    r4 = await client.post(
        "/api/files/upload",
        files={"file": ("fake.png", io.BytesIO(b"this is not a png"), "image/png")},
        headers=headers,
    )
    assert r4.status_code == 400


async def test_file_upload_rate_limit(client):
    headers = await login(client, PHONES["w_prod2"])
    content = b"\x89PNG\r\n\x1a\n" + b"1" * 20
    last = None
    for _ in range(20):
        last = await client.post(
            "/api/files/upload",
            files={"file": ("a.png", io.BytesIO(content), "image/png")},
            headers=headers,
        )
        assert last.status_code == 200
    r = await client.post(
        "/api/files/upload",
        files={"file": ("a.png", io.BytesIO(content), "image/png")},
        headers=headers,
    )
    assert r.status_code == 429


async def test_form_definition_versioning(client):
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.post(
        "/api/admin/forms",
        json={
            "department_code": "PRODUCTION", "code": "test_form_v", "title_en": "T", "title_hi": "T",
            "title_mr": "T",
            "schema_json": {"fields": [
                {"key": "a", "type": "text", "label_en": "A", "label_hi": "A", "label_mr": "A",
                 "required": True, "options": None, "ai_hook": None, "validation": {}}
            ]},
        },
        headers=mgr,
    )
    assert r.status_code == 200, r.text
    form = r.json()
    assert form["version"] == 1
    r = await client.patch(
        f"/api/admin/forms/{form['id']}",
        json={"schema_json": {"fields": [
            {"key": "a", "type": "text", "label_en": "A", "label_hi": "A", "label_mr": "A",
             "required": False, "options": None, "ai_hook": None, "validation": {}},
            {"key": "b", "type": "number", "label_en": "B", "label_hi": "B", "label_mr": "B",
             "required": False, "options": None, "ai_hook": None, "validation": {}},
        ]}},
        headers=mgr,
    )
    assert r.json()["version"] == 2
    # a worker of another dept cannot create forms
    w = await login(client, PHONES["w_eng"])
    r = await client.post(
        "/api/admin/forms",
        json={"department_code": "PRODUCTION", "code": "xx", "title_en": "x", "title_hi": "x",
              "title_mr": "x", "schema_json": {"fields": [
                  {"key": "a", "type": "text", "label_en": "A", "label_hi": "A", "label_mr": "A",
                   "required": True, "options": None, "ai_hook": None, "validation": {}}]}},
        headers=w,
    )
    assert r.status_code == 403


async def test_notifications_flow(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    r = await client.post(
        "/api/incidents",
        json={"category": "electrical", "department_code": "PRODUCTION", "photo_key": "n.jpg"},
        headers=w,
    )
    inc_id = r.json()["id"]
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/notifications/mine", headers=mgr)
    assert r.status_code == 200
    items = r.json()["items"]
    notif = next(n for n in items if n["entity_id"] == inc_id and n["type"] == "incident_assigned")
    assert notif["title_mr"]  # trilingual titles present
    r = await client.post(f"/api/notifications/{notif['id']}/read", headers=mgr)
    assert r.json()["is_read"] is True


async def test_departments_public_list(client):
    r = await client.get("/api/departments")
    assert r.status_code == 200
    codes = {d["code"] for d in r.json()}
    assert len(codes) == 13 and "TIME_OFFICE" in codes


async def test_admin_employee_search_cgm_only(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/employees", params={"search": "Worker Prod"}, headers=cgm)
    assert r.status_code == 200
    names = {e["full_name"] for e in r.json()}
    assert "Worker Prod1" in names
    # search by phone fragment
    r = await client.get("/api/admin/employees", params={"search": PHONES["w_eng"][-6:]}, headers=cgm)
    assert r.status_code == 200
    assert any(e["phone"] == PHONES["w_eng"] for e in r.json())
    # Manager (rank 3) is forbidden — CGM/MD only
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/admin/employees", params={"search": "Worker"}, headers=mgr)
    assert r.status_code == 403


async def test_admin_employee_missing_phone_filter(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/employees", params={"missing_phone": "true"}, headers=cgm)
    assert r.status_code == 200
    assert all(e["phone"] is None for e in r.json())

