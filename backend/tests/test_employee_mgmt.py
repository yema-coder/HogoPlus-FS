"""MD-dashboard Employee Management: full list scope, emp_id edits (UUID-safe),
phone change = immediate login-identity change, uniqueness collisions, audit."""
import pytest
from sqlalchemy import select

from app.models import Attendance, AuditEvent, Employee
from app.shift_logic import now_ist
from tests.conftest import PHONES, login, set_otp

P_A = "+919000000900"
P_B = "+919000000901"
P_NEW = "+919000000902"
EMP_IDS = ("E900", "E900X", "E901")


async def _purge(session):
    emps = (
        await session.execute(
            select(Employee).where(
                Employee.emp_id.in_(EMP_IDS) | Employee.phone.in_((P_A, P_B, P_NEW))
            )
        )
    ).scalars().all()
    if not emps:
        return
    ids = [e.id for e in emps]
    for att in (
        await session.execute(select(Attendance).where(Attendance.employee_id.in_(ids)))
    ).scalars():
        await session.delete(att)
    for ev in (
        await session.execute(select(AuditEvent).where(AuditEvent.actor_id.in_(ids)))
    ).scalars():
        await session.delete(ev)
    await session.flush()
    for e in emps:
        await session.delete(e)
    await session.commit()


@pytest.fixture
async def duo(db_session):
    """Two disposable approved workers so edits never pollute the shared cast."""
    await _purge(db_session)  # defensive: leftovers from a previously failed run
    rows = [
        Employee(
            emp_id="E900", full_name="Mgmt Test One", phone=P_A, department_code="STORE",
            designation="Worker", role_code="Worker", language_pref="mr",
            shift_swap_eligible=False, onboarding_status="approved", is_active=True,
        ),
        Employee(
            emp_id="E901", full_name="Mgmt Test Two", phone=P_B, department_code="STORE",
            designation="Worker", role_code="Worker", language_pref="mr",
            shift_swap_eligible=False, onboarding_status="approved", is_active=True,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    for r in rows:
        await db_session.refresh(r)
    yield rows
    await db_session.rollback()
    await _purge(db_session)


@pytest.mark.anyio
async def test_list_all_scope_md_cgm_only(client, db_session, duo):
    cgm = await login(client, PHONES["cgm"])
    # deactivate one so the full register must still include it
    duo[1].is_active = False
    await db_session.commit()
    r = await client.get("/api/admin/employees?all=true", headers=cgm)
    assert r.status_code == 200
    ids = {e["emp_id"] for e in r.json()}
    assert {"E900", "E901"} <= ids  # inactive row included
    # rank 3 (Time Office manager) may use the normal search but NOT the full register
    to = await login(client, PHONES["time_mgr"])
    assert (await client.get("/api/admin/employees?all=true", headers=to)).status_code == 403
    # rank 5 worker: no employee admin at all
    w = await login(client, PHONES["w_att1"])
    assert (await client.get("/api/admin/employees?all=true", headers=w)).status_code == 403
    duo[1].is_active = True
    await db_session.commit()


@pytest.mark.anyio
async def test_emp_id_change_is_uuid_safe_and_audited(client, db_session, duo):
    cgm = await login(client, PHONES["cgm"])
    emp = duo[0]
    # history BEFORE the change — attendance references the internal UUID
    att = Attendance(
        employee_id=emp.id, date=now_ist().date(), punch_in_at=now_ist(),
        selfie_key="test-selfie.jpg", verification_level="verified",
    )
    db_session.add(att)
    await db_session.commit()

    r = await client.patch(
        f"/api/admin/employees/{emp.id}", json={"emp_id": "E900X"}, headers=cgm
    )
    assert r.status_code == 200, r.text
    assert r.json()["emp_id"] == "E900X"
    # attendance row still attached to the same employee UUID — nothing orphaned
    await db_session.refresh(att)
    assert att.employee_id == emp.id
    # audit visible in the employee history endpoint with old -> new
    hist = (await client.get(f"/api/admin/employees/{emp.id}/history", headers=cgm)).json()
    upd = [h for h in hist if h["action"] == "employee.updated" and "emp_id" in h["detail"]]
    assert upd and upd[-1]["detail"]["emp_id"] == {"old": "E900", "new": "E900X"}


@pytest.mark.anyio
async def test_emp_id_uniqueness_and_rank_gate(client, db_session, duo):
    cgm = await login(client, PHONES["cgm"])
    # collision names the current holder
    r = await client.patch(
        f"/api/admin/employees/{duo[0].id}", json={"emp_id": "E901"}, headers=cgm
    )
    assert r.status_code == 409
    assert "Mgmt Test Two" in r.json()["detail"]
    # rank 3 cannot change emp_id (Time Office manager)
    to = await login(client, PHONES["time_mgr"])
    r = await client.patch(
        f"/api/admin/employees/{duo[0].id}", json={"emp_id": "E999"}, headers=to
    )
    assert r.status_code == 403
    # format validation
    r = await client.patch(
        f"/api/admin/employees/{duo[0].id}", json={"emp_id": "bad id!"}, headers=cgm
    )
    assert r.status_code == 422


@pytest.mark.anyio
async def test_phone_change_flips_login_identity_immediately(client, db_session, duo):
    cgm = await login(client, PHONES["cgm"])
    emp = duo[0]
    # session minted on the OLD number BEFORE the change (bound to UUID, must survive)
    code = await set_otp(P_A)
    pre = await client.post("/api/auth/verify-otp", json={"phone": P_A, "otp": code})
    assert pre.status_code == 200 and pre.json()["is_new"] is False
    old_session = {"Authorization": f"Bearer {pre.json()['access_token']}"}

    r = await client.patch(
        f"/api/admin/employees/{emp.id}", json={"phone": P_NEW}, headers=cgm
    )
    assert r.status_code == 200, r.text

    # OLD number is dead for login the moment the change commits: verify-otp no
    # longer resolves an employee — it falls into the self-registration path.
    code = await set_otp(P_A)
    old_try = await client.post("/api/auth/verify-otp", json={"phone": P_A, "otp": code})
    assert old_try.status_code == 200 and old_try.json().get("is_new") is True

    # NEW number logs into the SAME account instantly
    code = await set_otp(P_NEW)
    new_try = await client.post("/api/auth/verify-otp", json={"phone": P_NEW, "otp": code})
    assert new_try.status_code == 200
    body = new_try.json()
    assert body["is_new"] is False and body["employee"]["id"] == str(emp.id)

    # existing app session survives — tokens are bound to the employee UUID
    me = await client.get("/api/auth/me", headers=old_session)
    assert me.status_code == 200 and me.json()["id"] == str(emp.id)


@pytest.mark.anyio
async def test_phone_uniqueness_names_holder(client, db_session, duo):
    cgm = await login(client, PHONES["cgm"])
    r = await client.patch(
        f"/api/admin/employees/{duo[0].id}", json={"phone": P_B}, headers=cgm
    )
    assert r.status_code == 409
    assert "E901" in r.json()["detail"] and "Mgmt Test Two" in r.json()["detail"]
