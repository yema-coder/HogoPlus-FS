"""MD handover batch: two owner-provided numbers become MD-role logins with a
temporary password (Hogo@123, forced change), idempotently, fully audited."""
import pytest
from sqlalchemy import select

from app.models import AuditEvent, Employee
from scripts.seed_md_handover import MD_PHONES, TEMP_PASSWORD, apply_md_handover
from tests.conftest import login, set_otp


@pytest.fixture
async def md_candidates(db_session):
    """The two real phones exist in prod as Manager rows — mirror that here."""
    rows = []
    for i, (emp_id, name, phone, dept) in enumerate([
        ("0428", "Pathan Irfan Husen", MD_PHONES[0], "TIME_OFFICE"),
        ("1220", "Husen Pathan", MD_PHONES[1], "ADMIN"),
    ]):
        e = Employee(
            emp_id=emp_id, full_name=name, phone=phone, department_code=dept,
            designation="Manager", role_code="Manager", language_pref="mr",
            shift_swap_eligible=False, onboarding_status="approved", is_active=True,
        )
        db_session.add(e)
        rows.append(e)
    await db_session.commit()
    yield rows
    ids = [e.id for e in rows]
    for ev in (
        await db_session.execute(
            select(AuditEvent).where(
                (AuditEvent.action == "employee.md_handover") | AuditEvent.actor_id.in_(ids)
            )
        )
    ).scalars():
        await db_session.delete(ev)
    await db_session.flush()
    for e in rows:
        await db_session.delete(e)
    await db_session.commit()


@pytest.mark.anyio
async def test_md_handover_links_roles_and_audits(client, db_session, md_candidates):
    lines = await apply_md_handover(db_session)
    assert all("NO employee row" not in line for line in lines)
    for phone in MD_PHONES:
        emp = (
            await db_session.execute(select(Employee).where(Employee.phone == phone))
        ).scalar_one()
        assert emp.role_code == "MD"
        assert emp.must_change_password is True
        assert emp.password_hash is not None
        assert emp.is_active and emp.onboarding_status == "approved"
    audits = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.action == "employee.md_handover"))
    ).scalars().all()
    assert len(audits) == 2
    # owner CGM row untouched
    owner = (
        await db_session.execute(select(Employee).where(Employee.emp_id == "0001"))
    ).scalar_one()
    assert owner.role_code == "CGM"
    assert owner.password_hash is None  # test seed has no password; seed didn't add one


@pytest.mark.anyio
async def test_md_password_login_forces_change_for_both(client, db_session, md_candidates):
    await apply_md_handover(db_session)
    for emp_id in ("0428", "1220"):
        res = await client.post(
            "/api/auth/password-login", json={"emp_id": emp_id, "password": TEMP_PASSWORD}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["must_change_password"] is True
        assert body["employee"]["role"]["code"] == "MD"
        assert body["employee"]["role"]["rank"] == 1


@pytest.mark.anyio
async def test_md_otp_login_lands_with_md_role(client, db_session, md_candidates):
    await apply_md_handover(db_session)
    for phone in MD_PHONES:
        code = await set_otp(phone)
        res = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": code})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body.get("is_new") is not True
        assert body["employee"]["role"]["code"] == "MD"
        # dashboard-relevant permission smoke: MD may read admin settings
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        s = await client.get("/api/admin/settings", headers=headers)
        assert s.status_code == 200


@pytest.mark.anyio
async def test_md_handover_idempotent_never_resets_changed_password(client, db_session, md_candidates):
    await apply_md_handover(db_session)
    # first login + forced change
    res = await client.post(
        "/api/auth/password-login", json={"emp_id": "0428", "password": TEMP_PASSWORD}
    )
    token = res.json()["access_token"]
    ch = await client.post(
        "/api/auth/change-password",
        json={"current_password": TEMP_PASSWORD, "new_password": "NewSecret@99"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ch.status_code == 200
    # re-run the seed — must NOT reset the changed password
    db_session.expire_all()
    await apply_md_handover(db_session)
    old = await client.post(
        "/api/auth/password-login", json={"emp_id": "0428", "password": TEMP_PASSWORD}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/auth/password-login", json={"emp_id": "0428", "password": "NewSecret@99"}
    )
    assert new.status_code == 200
    assert new.json()["must_change_password"] is False
