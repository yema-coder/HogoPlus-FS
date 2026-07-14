from sqlalchemy import text

from tests.conftest import PHONES, login, set_otp

NEW_PHONE = "+919888888801"


async def _registration_token(client, phone: str = NEW_PHONE) -> str:
    code = await set_otp(phone)
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
    assert r.status_code == 200
    body = r.json()
    assert body["is_new"] is True
    return body["registration_token"]


async def _register(client):
    token = await _registration_token(client)
    return await client.post(
        "/api/auth/register",
        json={
            "phone": NEW_PHONE,
            "full_name": "New Worker",
            "department_code": "PRODUCTION",
            "selfie_key": "selfie123.jpg",
        },
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_register_without_token_401(client):
    r = await client.post(
        "/api/auth/register",
        json={
            "phone": "+919888888899",
            "full_name": "Sneaky Worker",
            "department_code": "PRODUCTION",
            "selfie_key": "s.jpg",
        },
    )
    assert r.status_code == 401


async def test_register_token_phone_mismatch_403(client):
    token = await _registration_token(client, phone="+919888888802")
    r = await client.post(
        "/api/auth/register",
        json={
            "phone": "+919888888803",
            "full_name": "Mismatch Worker",
            "department_code": "PRODUCTION",
            "selfie_key": "s.jpg",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


async def test_register_with_registration_token_creates_pending(client):
    r = await _register(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["employee"]["role_code"] == "Worker"
    assert body["employee"]["onboarding_status"] == "pending_approval"
    assert body["access_token"]


async def test_pending_user_cannot_access_forms(client):
    headers = await login(client, NEW_PHONE)
    r = await client.get("/api/forms", headers=headers)
    assert r.status_code == 403


async def test_pending_user_can_create_incident(client):
    headers = await login(client, NEW_PHONE)
    r = await client.post(
        "/api/incidents",
        json={"category": "safety", "department_code": "PRODUCTION", "photo_key": "p.jpg",
              "gps_lat": 19.0, "gps_lng": 74.7},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"


async def test_manager_approves_registration(client, db_session):
    emp_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": NEW_PHONE})
    ).scalar()
    headers = await login(client, PHONES["prod_mgr"])
    r = await client.post(f"/api/admin/employees/{emp_id}/approve", headers=headers)
    assert r.status_code == 200
    assert r.json()["onboarding_status"] == "approved"
    audit = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='employee.approved' AND entity_id=:e"),
            {"e": str(emp_id)},
        )
    ).scalar()
    assert audit >= 1


async def test_approved_user_can_now_access_forms(client):
    headers = await login(client, NEW_PHONE)
    r = await client.get("/api/forms", headers=headers)
    assert r.status_code == 200
    assert all(f["department_code"] == "PRODUCTION" for f in r.json())
