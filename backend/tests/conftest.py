import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["TESTING"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hogo:hogo_secret@127.0.0.1:5432/hogoplus_test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/5")
os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/6")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/7")
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["OTP_MODE"] = "demo"
os.environ["DEMO_OTP_ENABLED"] = "true"
os.environ["DEMO_OTP"] = "123456"
os.environ["FILE_STORAGE_MODE"] = "local"
os.environ["UPLOAD_DIR"] = "/tmp/hogo_test_uploads"
os.environ["ESCALATION_HOURS"] = "48"

DEMO_OTP = "123456"

PHONES = {
    "cgm": "+919000000001",
    "prod_mgr": "+919000000002",
    "time_mgr": "+919000000003",
    "w_prod1": "+919000000011",
    "w_prod2": "+919000000012",
    "w_prod3": "+919000000013",
    "w_eng": "+919000000014",
    "staff_prod": "+919000000015",
    "w_att1": "+919000000021",
    "w_att2": "+919000000022",
    "w_att3": "+919000000023",
    "w_att4": "+919000000024",
    "w_att5": "+919000000025",
}
# Seeded employee deliberately NOT in DEMO_OTP_WHITELIST — proves whitelist enforcement.
NON_WHITELISTED_PHONE = "+919000000031"
# These get registered/patched during tests and then log in via demo OTP:
# +919777777701 (test_admin_misc phone fix), +919888888801 (test_register new worker).
os.environ["DEMO_OTP_WHITELIST"] = ",".join(
    [*PHONES.values(), "+919777777701", "+919888888801"]
)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    BleBeacon,
    Department,
    Employee,
    FactorySettings,
    FormDefinition,
    Role,
    Shift,
    ShiftAssignment,
)

ROLES = [
    ("MD", 1), ("CGM", 2), ("Manager", 3), ("Staff", 4), ("Clerk", 5), ("Worker", 6),
]
DEPTS = [
    "ACCOUNTS", "ADMIN", "AGRICULTURE", "CANE_YARD", "CIVIL", "DISTILLERY",
    "ENGINEERING", "GODOWN", "PRODUCTION", "PURCHASE", "SECURITY", "STORE", "TIME_OFFICE",
]


async def _seed_base():
    from datetime import date, time

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as s:
        for code, rank in ROLES:
            s.add(Role(code=code, label_en=code, label_hi=code, label_mr=code, rank=rank))
        for code in DEPTS:
            s.add(Department(code=code, name_en=code.title(), name_hi=code, name_mr=code, is_active=True))
        s.add(Shift(code="A", label="Shift A", start_time=time(8, 0), end_time=time(16, 0)))
        s.add(Shift(code="B", label="Shift B", start_time=time(16, 0), end_time=time(0, 0)))
        s.add(Shift(code="C", label="Shift C", start_time=time(0, 0), end_time=time(8, 0)))
        s.add(Shift(code="GEN", label="General", start_time=time(9, 0), end_time=time(17, 30)))
        s.add(FactorySettings(factory_lat=19.0000, factory_lng=74.7000, radius_meters=500))
        await s.flush()

        def emp(emp_id, name, phone, dept, role, eligible=False, status="approved"):
            e = Employee(
                emp_id=emp_id, full_name=name, phone=phone, department_code=dept,
                designation=f"{role} {dept}", role_code=role, language_pref="mr",
                shift_swap_eligible=eligible, onboarding_status=status, is_active=True,
            )
            s.add(e)
            return e

        cgm = emp("0001", "Test CGM", PHONES["cgm"], "ADMIN", "CGM")
        prod_mgr = emp("0002", "Prod Manager", PHONES["prod_mgr"], "PRODUCTION", "Manager")
        time_mgr = emp("0003", "Time Manager", PHONES["time_mgr"], "TIME_OFFICE", "Manager")
        w1 = emp("0011", "Worker Prod1", PHONES["w_prod1"], "PRODUCTION", "Worker", eligible=True)
        w2 = emp("0012", "Worker Prod2", PHONES["w_prod2"], "PRODUCTION", "Worker", eligible=True)
        w3 = emp("0013", "Worker Prod3", PHONES["w_prod3"], "PRODUCTION", "Worker", eligible=True)
        weng = emp("0014", "Worker Eng", PHONES["w_eng"], "ENGINEERING", "Worker", eligible=True)
        emp("0015", "Staff Prod", PHONES["staff_prod"], "PRODUCTION", "Staff", eligible=False)
        wa1 = emp("0021", "Att Worker1", PHONES["w_att1"], "PRODUCTION", "Worker", eligible=True)
        wa2 = emp("0022", "Att Worker2", PHONES["w_att2"], "PRODUCTION", "Worker", eligible=True)
        wa3 = emp("0023", "Att Worker3", PHONES["w_att3"], "PRODUCTION", "Worker", eligible=True)
        wa4 = emp("0024", "Att Worker4", PHONES["w_att4"], "PRODUCTION", "Worker", eligible=True)
        wa5 = emp("0025", "Att Worker5", PHONES["w_att5"], "PRODUCTION", "Worker", eligible=True)
        emp("0031", "NoWhitelist Worker", NON_WHITELISTED_PHONE, "PRODUCTION", "Worker", eligible=True)
        emp("0120", "NoPhone Worker", None, "GODOWN", "Worker", eligible=True, status="seeded")
        await s.flush()

        # registered vendor beacons — MAC mode (iBeacon triple left NULL)
        s.add(BleBeacon(
            beacon_uuid=None, mac_address="AA:BB:CC:DD:EE:01", major=None, minor=None,
            zone_label_en="Mill Gate", zone_label_hi="मिल गेट", zone_label_mr="मिल गेट",
            department_code="SECURITY", is_active=True,
        ))
        s.add(BleBeacon(
            beacon_uuid=None, mac_address="AA:BB:CC:DD:EE:02", major=None, minor=None,
            zone_label_en="Old Gate", zone_label_hi="पुराना गेट", zone_label_mr="जुना गेट",
            department_code="SECURITY", is_active=False,
        ))
        # registered iBeacon (UUID/Major/Minor mode) — active
        s.add(BleBeacon(
            beacon_uuid="f7826da6-4fa2-4e98-8024-bc5b71e0893e", mac_address=None,
            major=1, minor=1,
            zone_label_en="Boiler House", zone_label_hi="बॉयलर हाउस", zone_label_mr="बॉयलर हाउस",
            department_code="PRODUCTION", is_active=True,
        ))
        await s.flush()

        # dept managers
        for code, mgr in (("PRODUCTION", prod_mgr), ("TIME_OFFICE", time_mgr)):
            d = (await s.execute(text("SELECT id FROM departments WHERE code=:c"), {"c": code})).first()
            await s.execute(
                text("UPDATE departments SET manager_employee_id=:m WHERE code=:c"),
                {"m": mgr.id, "c": code},
            )

        base = date(2025, 1, 1)
        for e, code in ((w1, "A"), (w2, "B"), (w3, "A"), (weng, "A"),
                        (wa1, "GEN"), (wa2, "GEN"), (wa3, "GEN"), (wa4, "GEN"), (wa5, "GEN"),
                        (cgm, "GEN"), (prod_mgr, "GEN"), (time_mgr, "GEN")):
            s.add(ShiftAssignment(employee_id=e.id, shift_code=code, effective_date=base, source="baseline"))

        s.add(FormDefinition(
            department_code="PRODUCTION", code="hourly_process_log",
            title_en="Hourly Process Log", title_hi="x", title_mr="x",
            schema_json={"fields": [
                {"key": "station", "type": "select", "label_en": "Station", "label_hi": "x", "label_mr": "x",
                 "required": True, "options": ["pan", "centrifugal", "evaporator", "lab"], "ai_hook": None, "validation": {}},
                {"key": "brix_value", "type": "number", "label_en": "Brix", "label_hi": "x", "label_mr": "x",
                 "required": True, "options": None, "ai_hook": None, "validation": {"min": 0, "max": 100}},
                {"key": "reading_photo", "type": "photo", "label_en": "Photo", "label_hi": "x", "label_mr": "x",
                 "required": False, "options": None, "ai_hook": "gauge_read", "validation": {}},
                {"key": "remarks", "type": "text", "label_en": "Remarks", "label_hi": "x", "label_mr": "x",
                 "required": False, "options": None, "ai_hook": None, "validation": {}},
            ]},
            version=1, is_active=True, requires_approval=True, approval_role_code="Manager",
        ))
        s.add(FormDefinition(
            department_code="ENGINEERING", code="job_card",
            title_en="Job Card", title_hi="x", title_mr="x",
            schema_json={"fields": [
                {"key": "asset_name", "type": "text", "label_en": "Asset", "label_hi": "x", "label_mr": "x",
                 "required": True, "options": None, "ai_hook": None, "validation": {}},
                {"key": "priority", "type": "select", "label_en": "Priority", "label_hi": "x", "label_mr": "x",
                 "required": True, "options": ["low", "normal", "urgent"], "ai_hook": None, "validation": {}},
            ]},
            version=1, is_active=True, requires_approval=True, approval_role_code="Manager",
        ))
        await s.commit()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    await _seed_base()
    yield


@pytest_asyncio.fixture(autouse=True)
async def flush_redis():
    from app.redis_client import redis_client

    await redis_client.flushdb()
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as s:
        yield s


async def login(client: AsyncClient, phone: str) -> dict:
    r = await client.post("/api/auth/verify-otp", json={"phone": phone, "otp": DEMO_OTP})
    assert r.status_code == 200, f"login failed for {phone}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def set_otp(phone: str, code: str = "654321") -> str:
    """Store a known OTP hash directly in Redis (mirrors send-otp) for unknown-phone tests."""
    import hashlib

    from app.redis_client import redis_client

    await redis_client.setex(f"otp:code:{phone}", 300, hashlib.sha256(code.encode()).hexdigest())
    return code


async def employee_id_by_phone(db_session, phone: str) -> str:
    row = (await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": phone})).first()
    return str(row[0])
