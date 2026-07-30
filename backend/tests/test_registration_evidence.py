"""v1.0.20: registration evidence (where/when/device) + pending-approval enrichment
(duplicate hints, geofence flag) + onboarding history endpoint."""
from sqlalchemy import select

from app.models import FactorySettings

from tests.conftest import PHONES, login, set_otp

PHONE = "+919888888821"


async def _register_with_context(client, db_session):
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    code = await set_otp(PHONE)
    r = await client.post("/api/auth/verify-otp", json={"phone": PHONE, "otp": code})
    token = r.json()["registration_token"]
    return await client.post(
        "/api/auth/register",
        json={
            "phone": PHONE,
            "full_name": "Ramesh Pawarr",  # near-duplicate of a seeded name is not
            "selfie_key": "selfie-ctx.jpg",  # guaranteed; duplicate test seeds its own
            "lat": fs.factory_lat,  # register exactly at the factory -> inside geofence
            "lng": fs.factory_lng,
            "address": "Factory Gate 1, Shrigonda",
            "device": "Samsung SM-A155F",
            "app_version": "1.0.20",
        },
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_register_stores_evidence_and_pending_is_enriched(client, db_session):
    r = await _register_with_context(client, db_session)
    assert r.status_code == 200, r.text

    to = await login(client, PHONES["time_mgr"])
    rows = (await client.get("/api/admin/employees/pending", headers=to)).json()
    mine = next(x for x in rows if x["phone"] == PHONE)
    assert mine["reg_inside_geofence"] is True
    assert mine["reg_address"] == "Factory Gate 1, Shrigonda"
    assert mine["reg_device"] == "Samsung SM-A155F"
    assert mine["reg_app_version"] == "1.0.20"
    assert mine["created_at"]  # registered-at timestamp for the approver
    assert isinstance(mine["duplicate_hints"], list)
    assert len(mine["suggested_emp_id"]) == 4


async def test_duplicate_name_warning(client, db_session):
    # a second registrant whose name nearly matches an approved employee
    approved_name = "Ramesh Pawar Duplicate Check"
    from app.models import Employee

    db_session.add(
        Employee(
            emp_id="1901", full_name=approved_name, phone="+919888888822",
            department_code="PRODUCTION", designation="Worker PRODUCTION",
            role_code="Worker", language_pref="mr", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True,
        )
    )
    await db_session.commit()
    phone = "+919888888823"
    code = await set_otp(phone)
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
    token = r.json()["registration_token"]
    r = await client.post(
        "/api/auth/register",
        json={"phone": phone, "full_name": "Ramesh Pawar Duplicate Chek",
              "selfie_key": "s2.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    to = await login(client, PHONES["time_mgr"])
    rows = (await client.get("/api/admin/employees/pending", headers=to)).json()
    mine = next(x for x in rows if x["phone"] == phone)
    assert any(h["full_name"] == approved_name for h in mine["duplicate_hints"])
    # no location sent -> geofence unknown, not false
    assert mine["reg_inside_geofence"] is None


async def test_onboarding_history_shows_approver(client, db_session):
    to = await login(client, PHONES["time_mgr"])
    rows = (await client.get("/api/admin/employees/pending", headers=to)).json()
    mine = next(x for x in rows if x["phone"] == PHONE)
    r = await client.post(
        f"/api/admin/employees/{mine['id']}/approve",
        json={"emp_id": mine["suggested_emp_id"], "department_code": "PRODUCTION",
              "role_code": "Worker"},
        headers=to,
    )
    assert r.status_code == 200, r.text
    hist = (await client.get(f"/api/admin/employees/{mine['id']}/history", headers=to)).json()
    approved = [h for h in hist if h["action"] == "employee.approved"]
    assert approved and approved[0]["by"]  # who approved
    assert approved[0]["at"]  # and when
