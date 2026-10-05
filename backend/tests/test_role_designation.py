"""Phase A: role (permissions) and designation (job title) are STRICTLY separate."""
import pytest
from sqlalchemy import select

from app.models import Employee
from tests.conftest import PHONES, login


@pytest.mark.asyncio
async def test_roles_catalog(client):
    hdr = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/roles", headers=hdr)
    assert r.status_code == 200
    codes = {x["code"] for x in r.json()["roles"]}
    assert {"MD", "CGM", "Manager", "Staff", "Clerk", "Worker"} <= codes
    # CGM can assign every role
    assert all(x["assignable"] for x in r.json()["roles"])


@pytest.mark.asyncio
async def test_time_office_cannot_assign_top_roles(client):
    hdr = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/admin/roles", headers=hdr)
    assert r.status_code == 200
    by = {x["code"]: x["assignable"] for x in r.json()["roles"]}
    assert by["MD"] is False and by["CGM"] is False
    assert by["Manager"] is True and by["Worker"] is True


@pytest.mark.asyncio
async def test_patch_sets_role_and_designation_independently(client, db_session):
    hdr = await login(client, PHONES["cgm"])
    emp = (await db_session.execute(select(Employee).where(Employee.phone == PHONES["w_prod3"]))).scalar_one()
    r = await client.patch(
        f"/api/admin/employees/{emp.id}",
        json={"role_code": "Clerk", "designation": "Fieldman"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role_code"] == "Clerk"       # permission role
    assert body["designation"] == "Fieldman"  # job title — NOT derived from role
    await db_session.refresh(emp)
    assert emp.role_code == "Clerk" and emp.designation == "Fieldman"


@pytest.mark.asyncio
async def test_direct_add_keeps_role_and_designation_separate(client):
    hdr = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/admin/employees",
        json={
            "full_name": "Sep Test", "phone": "+919000000077",
            "department_code": "AGRICULTURE", "role_code": "Worker",
            "emp_id": "SEP77", "designation": "Slipboy",
        },
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role_code"] == "Worker"
    assert body["designation"] == "Slipboy"
