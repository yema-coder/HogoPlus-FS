from sqlalchemy import text

from tests.conftest import DEMO_OTP, PHONES, login, set_otp


async def test_send_otp_success(client):
    r = await client.post("/api/auth/send-otp", json={"phone": PHONES["w_prod1"]})
    assert r.status_code == 200
    assert r.json()["otp_mode"] == "demo"


async def test_send_otp_invalid_phone(client):
    r = await client.post("/api/auth/send-otp", json={"phone": "12345"})
    assert r.status_code == 422


async def test_send_otp_rate_limit(client):
    phone = PHONES["w_prod1"]
    for _ in range(3):
        r = await client.post("/api/auth/send-otp", json={"phone": phone})
        assert r.status_code == 200
    r = await client.post("/api/auth/send-otp", json={"phone": phone})
    assert r.status_code == 429


async def test_verify_wrong_otp(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONES["w_prod1"], "otp": "000000"})
    assert r.status_code == 401


async def test_verify_lockout_after_5_wrong(client):
    phone = PHONES["w_prod2"]
    for i in range(4):
        r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": "000000"})
        assert r.status_code == 401
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": "000000"})
    assert r.status_code == 429  # 5th wrong attempt triggers lockout
    # even the correct demo OTP is now rejected
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": DEMO_OTP})
    assert r.status_code == 429


async def test_verify_demo_success(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONES["w_prod1"], "otp": DEMO_OTP})
    assert r.status_code == 200
    body = r.json()
    assert body["is_new"] is False
    assert body["access_token"] and body["refresh_token"]
    assert body["employee"]["emp_id"] == "0011"
    assert body["employee"]["role"]["rank"] == 6


async def test_verify_unknown_phone_is_new_with_registration_token(client):
    phone = "+919999999999"
    code = await set_otp(phone)
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
    assert r.status_code == 200
    body = r.json()
    assert body["is_new"] is True
    assert body["registration_token"]
    assert "access_token" not in body


async def test_demo_otp_rejected_for_unknown_phone(client):
    # DEMO_OTP shortcut must never work for phones not present in the employees table
    r = await client.post("/api/auth/verify-otp", json={"phone": "+919999999988", "otp": DEMO_OTP})
    assert r.status_code == 401


async def test_refresh_token(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONES["w_prod1"], "otp": DEMO_OTP})
    refresh = r.json()["refresh_token"]
    r2 = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200
    new_access = r2.json()["access_token"]
    r3 = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert r3.status_code == 200


async def test_refresh_with_access_token_rejected(client):
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONES["w_prod1"], "otp": DEMO_OTP})
    access = r.json()["access_token"]
    r2 = await client.post("/api/auth/refresh", json={"refresh_token": access})
    assert r2.status_code == 401


async def test_me_requires_auth(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_returns_profile(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["role_code"] == "CGM"


async def test_patch_me_language(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.patch("/api/employees/me", json={"language_pref": "hi"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["language_pref"] == "hi"
    # invalid language rejected
    r = await client.patch("/api/employees/me", json={"language_pref": "xx"}, headers=headers)
    assert r.status_code == 422
    await client.patch("/api/employees/me", json={"language_pref": "mr"}, headers=headers)


async def test_login_writes_audit(client, db_session):
    await login(client, PHONES["w_prod3"])
    row = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM audit_events a JOIN employees e ON a.actor_id=e.id "
                "WHERE a.action='auth.login' AND e.phone=:p"
            ),
            {"p": PHONES["w_prod3"]},
        )
    ).scalar()
    assert row >= 1
