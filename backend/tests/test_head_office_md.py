"""v1.0.24 batch: HEAD_OFFICE department policy + MD access redesign.

Covers scripts/seed_head_office_md.py (idempotent EC2 data script) and the new
endpoints: /auth/md-login (shared password, no emp_id), /auth/md-elevate
(OTP whitelist), /admin/employees/availability, and the per-department
can_add_employees / beacon_exempt / geofence_exempt policy flags.
"""
import pytest_asyncio
from sqlalchemy import delete, func, or_, select

from app.models import (
    Attendance,
    AuditEvent,
    Department,
    Employee,
    FactorySettings,
    Notification,
    ShiftAssignment,
)
from scripts.seed_head_office_md import (
    DEMOTE_PHONES,
    HO_CODE,
    HO_MANAGER_NAME,
    HO_MANAGER_PHONE,
    INITIAL_MD_PASSWORD,
    MD_OTP_PHONES,
    SHARED_MD_EMP_ID,
    apply,
)
from tests.conftest import PHONES, login, set_otp

NEW_WORKER_PHONE = "+919555000111"
CLEANUP_PHONES = [HO_MANAGER_PHONE, NEW_WORKER_PHONE, "+919555000222", *DEMOTE_PHONES]


async def _teardown(s):
    """Remove every row this file creates so the rest of the suite sees baseline."""
    dept = (
        await s.execute(select(Department).where(Department.code == HO_CODE))
    ).scalar_one_or_none()
    if dept is not None:
        dept.manager_employee_id = None
        await s.flush()
    rows = (
        await s.execute(
            select(Employee).where(
                or_(Employee.emp_id == SHARED_MD_EMP_ID, Employee.phone.in_(CLEANUP_PHONES))
            )
        )
    ).scalars().all()
    ids = [e.id for e in rows]
    if ids:
        str_ids = [str(i) for i in ids]
        await s.execute(delete(Notification).where(Notification.recipient_id.in_(ids)))
        await s.execute(
            delete(AuditEvent).where(
                or_(AuditEvent.actor_id.in_(ids), AuditEvent.entity_id.in_(str_ids))
            )
        )
        await s.execute(delete(Attendance).where(Attendance.employee_id.in_(ids)))
        await s.execute(delete(ShiftAssignment).where(ShiftAssignment.employee_id.in_(ids)))
        for e in rows:
            await s.delete(e)
        await s.flush()
    if dept is not None:
        await s.delete(dept)
    to = (
        await s.execute(select(Department).where(Department.code == "TIME_OFFICE"))
    ).scalar_one_or_none()
    if to is not None:
        to.can_add_employees = False
    fs = (await s.execute(select(FactorySettings))).scalars().first()
    if fs is not None:
        fs.md_password_hash = None
        fs.md_otp_phones = ""
        fs.beacon_first_mode = False
    await s.execute(
        delete(AuditEvent).where(
            AuditEvent.action.in_(["auth.md_login_failed", "admin.md_password_changed"])
        )
    )
    await s.commit()


@pytest_asyncio.fixture
async def ho_seeded(db_session):
    """Mirror prod (two old-MD numbers hold MD role + passwords), then run the script."""
    from app.security import hash_password

    for i, phone in enumerate(DEMOTE_PHONES):
        db_session.add(Employee(
            emp_id=f"077{i}", full_name=f"Old MD {i}", phone=phone,
            department_code="ADMIN", designation="MD", role_code="MD",
            language_pref="mr", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True,
            password_hash=hash_password("OldPass@123"), must_change_password=True,
        ))
    await db_session.commit()
    lines = await apply(db_session)
    yield lines
    await _teardown(db_session)


# ---------------------------------------------------------------- seed script

async def test_seed_final_state_and_idempotency(client, db_session, ho_seeded):
    from app.security import hash_password, verify_password

    dept = (
        await db_session.execute(select(Department).where(Department.code == HO_CODE))
    ).scalar_one()
    assert dept.beacon_exempt and dept.geofence_exempt and dept.can_add_employees

    mgr = (
        await db_session.execute(select(Employee).where(Employee.phone == HO_MANAGER_PHONE))
    ).scalar_one()
    assert mgr.full_name == HO_MANAGER_NAME == "Mahesh Makne"
    assert mgr.role_code == "Manager" and mgr.department_code == HO_CODE
    assert dept.manager_employee_id == mgr.id

    md = (
        await db_session.execute(select(Employee).where(Employee.emp_id == SHARED_MD_EMP_ID))
    ).scalar_one()
    assert md.full_name == "Prasad Sugar Mill"
    assert md.role_code == "MD" and md.phone is None and md.password_hash is None

    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    assert fs.md_otp_phones == MD_OTP_PHONES
    assert verify_password(INITIAL_MD_PASSWORD, fs.md_password_hash)

    for phone in DEMOTE_PHONES:
        e = (
            await db_session.execute(select(Employee).where(Employee.phone == phone))
        ).scalar_one()
        assert e.role_code == "Manager" and e.password_hash is None

    # idempotent re-run — and a CHANGED password is never reset back to Hogo@123
    fs.md_password_hash = hash_password("Changed@9999")
    await db_session.commit()
    lines = await apply(db_session)
    assert any("NOT touched" in line for line in lines)
    fs2 = (await db_session.execute(select(FactorySettings))).scalars().first()
    assert verify_password("Changed@9999", fs2.md_password_hash)
    n = (
        await db_session.execute(
            select(func.count()).select_from(Employee).where(Employee.phone == HO_MANAGER_PHONE)
        )
    ).scalar()
    assert n == 1


# ---------------------------------------------------------------- md-login

async def test_md_login_password_only(client, db_session, ho_seeded):
    r = await client.post("/api/auth/md-login", json={"password": INITIAL_MD_PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["employee"]["emp_id"] == "MD"
    assert body["employee"]["role_code"] == "MD"
    assert body["employee"]["full_name"] == "Prasad Sugar Mill"
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["role_code"] == "MD"
    n = (
        await db_session.execute(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "auth.md_login")
        )
    ).scalar()
    assert n >= 1


async def test_md_login_lockout_and_failure_audit(client, db_session, ho_seeded):
    for _ in range(5):
        r = await client.post("/api/auth/md-login", json={"password": "WrongPass!"})
        assert r.status_code == 401
    # 6th attempt — even with the RIGHT password — is rate-limited
    r = await client.post("/api/auth/md-login", json={"password": INITIAL_MD_PASSWORD})
    assert r.status_code == 429
    fails = (
        await db_session.execute(
            select(func.count()).select_from(AuditEvent)
            .where(AuditEvent.action == "auth.md_login_failed")
        )
    ).scalar()
    assert fails == 5


async def test_legacy_password_login_rejects_shared_md(client, ho_seeded):
    # the shared account has NO personal password — emp_id path must stay closed
    r = await client.post(
        "/api/auth/password-login", json={"emp_id": "MD", "password": INITIAL_MD_PASSWORD}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------- md-elevate

async def test_md_elevate_whitelisted_number(client, db_session, ho_seeded):
    code = await set_otp(HO_MANAGER_PHONE)
    r = await client.post("/api/auth/verify-otp", json={"phone": HO_MANAGER_PHONE, "otp": code})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r2 = await client.post("/api/auth/md-elevate", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["employee"]["role_code"] == "MD"
    ev = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "auth.md_elevate")
            .order_by(AuditEvent.created_at.desc()).limit(1)
        )
    ).scalars().first()
    assert ev is not None and ev.detail_json["phone"] == HO_MANAGER_PHONE


async def test_md_elevate_rejects_non_whitelisted(client, ho_seeded):
    cgm_headers = await login(client, PHONES["cgm"])
    r = await client.post("/api/auth/md-elevate", headers=cgm_headers)
    assert r.status_code == 403


# ---------------------------------------------------------------- wizard APIs

async def test_availability_names_holder(client, ho_seeded):
    headers = await login(client, PHONES["time_mgr"])
    r = await client.get(
        "/api/admin/employees/availability", params={"emp_id": "0001"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert "Test CGM" in (r.json()["emp_id_taken_by"] or "")
    r = await client.get(
        "/api/admin/employees/availability", params={"phone": PHONES["w_prod1"]}, headers=headers
    )
    assert "Worker Prod1" in (r.json()["phone_taken_by"] or "")
    r = await client.get(
        "/api/admin/employees/availability",
        params={"emp_id": "9998", "phone": "+919999999998"}, headers=headers,
    )
    j = r.json()
    assert j["emp_id_taken_by"] is None and j["phone_taken_by"] is None


async def test_ho_manager_can_add_employee_other_managers_cannot(client, db_session, ho_seeded):
    code = await set_otp(HO_MANAGER_PHONE)
    r = await client.post("/api/auth/verify-otp", json={"phone": HO_MANAGER_PHONE, "otp": code})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert r.json()["employee"]["can_add_employees"] is True

    rs = await client.get("/api/admin/emp-id-suggest", headers=headers)
    assert rs.status_code == 200, rs.text
    emp_id = rs.json()["suggested_emp_id"]

    ra = await client.post("/api/admin/employees", headers=headers, json={
        "full_name": "HO Test Clerk", "phone": NEW_WORKER_PHONE,
        "department_code": HO_CODE, "role_code": "Clerk", "emp_id": emp_id,
    })
    assert ra.status_code == 200, ra.text
    assert ra.json()["department_code"] == HO_CODE

    # HO manager (rank 3) may NOT create CGM/MD accounts
    rb = await client.post("/api/admin/employees", headers=headers, json={
        "full_name": "Sneaky MD", "phone": "+919555000222",
        "department_code": HO_CODE, "role_code": "MD", "emp_id": "9977",
    })
    assert rb.status_code == 403

    # a manager of a department WITHOUT the flag stays locked out
    prod_headers = await login(client, PHONES["prod_mgr"])
    rc = await client.get("/api/admin/emp-id-suggest", headers=prod_headers)
    assert rc.status_code == 403
    rd = await client.post("/api/admin/employees", headers=prod_headers, json={
        "full_name": "X Y", "phone": "+919555000333",
        "department_code": "PRODUCTION", "role_code": "Worker", "emp_id": "9976",
    })
    assert rd.status_code == 403


# ------------------------------------------------- location policy exemptions

async def test_head_office_punch_beacon_and_geofence_exempt(client, db_session, ho_seeded):
    # harshest case: beacon-first mode ON + GPS in Pune (~100 km outside geofence)
    fs = (await db_session.execute(select(FactorySettings))).scalars().first()
    fs.beacon_first_mode = True
    await db_session.commit()

    code = await set_otp(HO_MANAGER_PHONE)
    r = await client.post("/api/auth/verify-otp", json={"phone": HO_MANAGER_PHONE, "otp": code})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    rp = await client.post("/api/attendance/punch-in", headers=headers, json={
        "gps_lat": 18.5204, "gps_lng": 73.8567, "selfie_key": "ho1.jpg",
    })
    assert rp.status_code == 200, rp.text
    assert rp.json()["verification_level"] == "verified"

    # control: an ADMIN-department account at the same spot IS flagged
    code2 = await set_otp(DEMOTE_PHONES[0])
    r2 = await client.post("/api/auth/verify-otp", json={"phone": DEMOTE_PHONES[0], "otp": code2})
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    rw = await client.post("/api/attendance/punch-in", headers=h2, json={
        "gps_lat": 18.5204, "gps_lng": 73.8567, "selfie_key": "ctl1.jpg",
    })
    assert rw.status_code == 200, rw.text
    assert rw.json()["verification_level"] == "flagged"
