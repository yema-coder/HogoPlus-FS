"""Idempotent seed of Wave-1 home configs (SECURITY, TIME_OFFICE, CGM/MD strip).

Safe to run against production: while settings.home_config_enabled is FALSE these
configs are only visible inside the demo bubble. Re-running upserts in place.

Usage: cd /app/backend && python scripts/seed_home_configs.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SECURITY_HOME = {
    "widgets": [
        {
            "type": "count_tiles",
            "items": [
                {"key": "vehicles_today_in", "route": "/vehicle", "emoji": "🚛",
                 "label": {"en": "In today", "hi": "आज अंदर", "mr": "आज आत"}},
                {"key": "vehicles_inside", "route": "/vehicle", "emoji": "🅿️",
                 "label": {"en": "Inside now", "hi": "अभी अंदर", "mr": "आत्ता आत"}},
            ],
        },
        {
            "type": "action_grid",
            "items": [
                {"icon": "Truck", "route": "/vehicle/new", "testID": "w-vehicle-new",
                 "label": {"en": "Vehicle entry", "hi": "वाहन एंट्री", "mr": "वाहन नोंद"}},
                {"icon": "ClipboardList", "route": "/vehicle", "testID": "w-vehicle-log",
                 "label": {"en": "Gate log", "hi": "गेट लॉग", "mr": "गेट नोंदवही"}},
                {"icon": "AlertTriangle", "route": "/incident/capture", "color": "#B3261E",
                 "label": {"en": "Incident", "hi": "शिकायत", "mr": "तक्रार"}},
                {"icon": "BookOpen", "route": "/sahayak",
                 "label": {"en": "Sahayak", "hi": "सहायक", "mr": "सहाय्यक"}},
            ],
        },
    ]
}

TIME_OFFICE_HOME = {
    "widgets": [
        {
            "type": "count_tiles",
            "items": [
                {"key": "pending_registrations", "route": "/(tabs)/approvals", "emoji": "🧾",
                 "label": {"en": "Registrations", "hi": "पंजीकरण", "mr": "नोंदणी"}},
                {"key": "flagged_attendance", "route": "/(tabs)/approvals", "emoji": "🚩",
                 "label": {"en": "Flagged punches", "hi": "फ्लैग पंच", "mr": "फ्लॅग पंच"}},
                {"key": "pending_submissions", "route": "/(tabs)/approvals", "emoji": "📋",
                 "label": {"en": "Form approvals", "hi": "फॉर्म मंजूरी", "mr": "फॉर्म मंजुरी"}},
                {"key": "phoneless_employees", "route": "/employees", "emoji": "📵",
                 "label": {"en": "No phone", "hi": "फोन नहीं", "mr": "फोन नाही"}},
            ],
        },
        {
            "type": "action_grid",
            "items": [
                {"icon": "CheckSquare", "route": "/(tabs)/approvals", "testID": "w-to-approvals",
                 "label": {"en": "Approval queue", "hi": "मंजूरी कतार", "mr": "मंजुरी रांग"}},
                {"icon": "Search", "route": "/employees",
                 "label": {"en": "Find employee", "hi": "कर्मचारी खोजें", "mr": "कर्मचारी शोधा"}},
                {"icon": "UserPlus", "route": "/employees/new",
                 "label": {"en": "Add employee", "hi": "कर्मचारी जोड़ें", "mr": "कर्मचारी जोडा"}},
                {"icon": "Clock", "route": "/attendance/history",
                 "label": {"en": "Attendance", "hi": "उपस्थिति", "mr": "हजेरी"}},
            ],
        },
    ]
}

MGMT_HOME = {
    "widgets": [
        {
            "type": "count_tiles",
            "items": [
                {"key": "present_today", "emoji": "👷",
                 "label": {"en": "Present today", "hi": "आज उपस्थित", "mr": "आज हजर"}},
                {"key": "open_incidents", "emoji": "⚠️",
                 "label": {"en": "Open complaints", "hi": "खुली शिकायतें", "mr": "खुल्या तक्रारी"}},
                {"key": "pending_registrations", "route": "/(tabs)/approvals", "emoji": "🧾",
                 "label": {"en": "Registrations", "hi": "पंजीकरण", "mr": "नोंदणी"}},
                {"key": "pending_submissions", "route": "/(tabs)/approvals", "emoji": "📋",
                 "label": {"en": "Approvals", "hi": "मंजूरी", "mr": "मंजुरी"}},
            ],
        },
        {
            "type": "action_grid",
            "items": [
                {"icon": "Megaphone", "route": "/announce",
                 "label": {"en": "Announce", "hi": "घोषणा", "mr": "घोषणा"}},
                {"icon": "Building2", "route": "/(tabs)/department",
                 "label": {"en": "Departments", "hi": "विभाग", "mr": "विभाग"}},
                {"icon": "CheckSquare", "route": "/(tabs)/approvals",
                 "label": {"en": "Approvals", "hi": "मंजूरी", "mr": "मंजुरी"}},
                {"icon": "BookOpen", "route": "/sahayak",
                 "label": {"en": "Sahayak", "hi": "सहायक", "mr": "सहाय्यक"}},
            ],
        },
    ]
}

CONFIGS = [
    ("SECURITY", None, SECURITY_HOME),
    ("TIME_OFFICE", None, TIME_OFFICE_HOME),
    (None, "CGM", MGMT_HOME),
    (None, "MD", MGMT_HOME),
]


async def main() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.models import HomeConfig

    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sm() as session:
        for dept, role, cfg in CONFIGS:
            row = (
                await session.execute(
                    select(HomeConfig).where(
                        HomeConfig.department_code.is_(None) if dept is None else HomeConfig.department_code == dept,
                        HomeConfig.role_code.is_(None) if role is None else HomeConfig.role_code == role,
                    )
                )
            ).scalar_one_or_none()
            if row:
                row.config_json = cfg
                row.is_active = True
                print(f"updated ({dept}, {role})")
            else:
                session.add(HomeConfig(department_code=dept, role_code=role, config_json=cfg, is_active=True))
                print(f"created ({dept}, {role})")
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
