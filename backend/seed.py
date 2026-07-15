"""Idempotent seed script — safe to re-run.
Seeds: 6 roles, 13 departments, 4 shifts, settings row, 401 employees from
seed_employees.csv, baseline shift assignments, department managers, 13 form definitions.

Run: cd /app/backend && python seed.py
"""
import asyncio
import csv
from datetime import date, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import (
    Department,
    Employee,
    FactorySettings,
    FormDefinition,
    Role,
    Shift,
    ShiftAssignment,
)
from app.shift_logic import SHIFT_A_DEPARTMENTS

CSV_PATH = Path(__file__).resolve().parent / "seed_employees.csv"
BASELINE_DATE = date(2025, 1, 1)

ROLES = [
    ("MD", "Managing Director", "प्रबंध निदेशक", "व्यवस्थापकीय संचालक", 1),
    ("CGM", "Chief General Manager", "मुख्य महाप्रबंधक", "मुख्य महाव्यवस्थापक", 2),
    ("Manager", "Manager", "प्रबंधक", "व्यवस्थापक", 3),
    ("Staff", "Staff", "स्टाफ", "कर्मचारी", 4),
    ("Clerk", "Clerk", "लिपिक", "लिपिक", 5),
    ("Worker", "Worker", "श्रमिक", "कामगार", 6),
]

DEPARTMENTS = [
    ("ACCOUNTS", "Accounts", "लेखा", "लेखा"),
    ("ADMIN", "Administration", "प्रशासन", "प्रशासन"),
    ("AGRICULTURE", "Agriculture", "कृषि", "शेती"),
    ("CANE_YARD", "Cane Yard", "केन यार्ड", "ऊस यार्ड"),
    ("CIVIL", "Civil", "सिविल", "सिव्हिल"),
    ("DISTILLERY", "Distillery", "डिस्टिलरी", "डिस्टिलरी"),
    ("ENGINEERING", "Engineering", "इंजीनियरिंग", "अभियांत्रिकी"),
    ("GODOWN", "Godown", "गोदाम", "गोदाम"),
    ("PRODUCTION", "Production", "उत्पादन", "उत्पादन"),
    ("PURCHASE", "Purchase", "खरीद", "खरेदी"),
    ("SECURITY", "Security", "सुरक्षा", "सुरक्षा"),
    ("STORE", "Store", "स्टोर", "स्टोअर"),
    ("TIME_OFFICE", "Time Office", "टाइम ऑफिस", "टाइम ऑफिस"),
]

SHIFTS = [
    ("A", "Shift A (08:00-16:00)", time(8, 0), time(16, 0)),
    ("B", "Shift B (16:00-00:00)", time(16, 0), time(0, 0)),
    ("C", "Shift C (00:00-08:00)", time(0, 0), time(8, 0)),
    ("GEN", "General (09:00-17:30)", time(9, 0), time(17, 30)),
]


def fld(key, type_, en, hi, mr, required=True, options=None, ai_hook=None, validation=None):
    return {
        "key": key, "type": type_, "label_en": en, "label_hi": hi, "label_mr": mr,
        "required": required, "options": options if options is not None else ([] if type_ == "select" else None),
        "ai_hook": ai_hook, "validation": validation or {},
    }


DEPT_OPTIONS = [d[0] for d in DEPARTMENTS]

FORMS = [
    ("CANE_YARD", "weighment_capture", "Weighment Capture", "तौल कैप्चर", "वजन नोंद", [
        fld("truck_plate", "text", "Truck Plate No.", "ट्रक नंबर", "ट्रक क्रमांक", ai_hook="anpr"),
        fld("weighment_display_photo", "photo", "Weighbridge Display Photo", "तौल डिस्प्ले फोटो", "वजन काटा फोटो"),
        fld("gross_weight_kg", "number", "Gross Weight (kg)", "कुल वजन (किग्रा)", "एकूण वजन (किलो)", validation={"min": 0, "max": 100000}),
        fld("farmer_code", "text", "Farmer Code", "किसान कोड", "शेतकरी कोड"),
        fld("remarks", "text", "Remarks", "टिप्पणी", "शेरा", required=False),
    ]),
    ("ENGINEERING", "job_card", "Job Card", "जॉब कार्ड", "जॉब कार्ड", [
        fld("asset_name", "text", "Asset / Machine", "मशीन का नाम", "यंत्राचे नाव"),
        fld("discipline", "select", "Discipline", "विभाग", "शाखा", options=["mechanical", "electrical", "instrumentation"]),
        fld("problem_description", "text", "Problem Description", "समस्या विवरण", "समस्येचे वर्णन"),
        fld("before_photo", "photo", "Before Photo", "पहले का फोटो", "आधीचा फोटो", required=False),
        fld("priority", "select", "Priority", "प्राथमिकता", "प्राधान्य", options=["low", "normal", "urgent"]),
        fld("parts_needed", "text", "Parts Needed", "आवश्यक पुर्जे", "आवश्यक भाग", required=False),
    ]),
    ("PRODUCTION", "hourly_process_log", "Hourly Process Log", "प्रति घंटा प्रोसेस लॉग", "तासाभराची प्रक्रिया नोंद", [
        fld("station", "select", "Station", "स्टेशन", "स्टेशन", options=["pan", "centrifugal", "evaporator", "lab"]),
        fld("reading_photo", "photo", "Gauge Reading Photo", "गेज रीडिंग फोटो", "गेज रीडिंग फोटो", ai_hook="gauge_read"),
        fld("brix_value", "number", "Brix Value", "ब्रिक्स मान", "ब्रिक्स मूल्य", validation={"min": 0, "max": 100}),
        fld("remarks", "text", "Remarks", "टिप्पणी", "शेरा", required=False),
    ]),
    ("DISTILLERY", "batch_log", "Batch Log", "बैच लॉग", "बॅच नोंद", [
        fld("tank_no", "text", "Tank No.", "टैंक नंबर", "टाकी क्रमांक"),
        fld("stage", "select", "Stage", "चरण", "टप्पा", options=["fermentation", "distillation", "storage"]),
        fld("gauge_photo", "photo", "Gauge Photo", "गेज फोटो", "गेज फोटो", ai_hook="gauge_read"),
        fld("reading_value", "number", "Reading Value", "रीडिंग मान", "रीडिंग मूल्य"),
        fld("remarks", "text", "Remarks", "टिप्पणी", "शेरा", required=False),
    ]),
    ("STORE", "material_issue", "Material Issue", "सामग्री निर्गम", "साहित्य वाटप", [
        fld("item_name", "text", "Item Name", "वस्तु का नाम", "वस्तूचे नाव"),
        fld("quantity", "number", "Quantity", "मात्रा", "प्रमाण", validation={"min": 0}),
        fld("issued_to_department", "select", "Issued To Department", "विभाग को जारी", "विभागाला दिले", options=DEPT_OPTIONS),
        fld("indent_ref", "text", "Indent Ref.", "इंडेंट संदर्भ", "इंडेंट संदर्भ"),
        fld("photo", "photo", "Photo", "फोटो", "फोटो", required=False),
    ]),
    ("GODOWN", "bag_movement", "Bag Movement", "बैग मूवमेंट", "पोती हालचाल", [
        fld("movement", "select", "Movement", "मूवमेंट", "हालचाल", options=["inward", "outward"]),
        fld("bag_count", "number", "Bag Count", "बैग संख्या", "पोती संख्या", validation={"min": 1}),
        fld("vehicle_plate", "text", "Vehicle Plate", "वाहन नंबर", "वाहन क्रमांक", ai_hook="anpr"),
        fld("gate_pass_photo", "photo", "Gate Pass Photo", "गेट पास फोटो", "गेट पास फोटो"),
    ]),
    ("PURCHASE", "indent_review", "Indent Review", "इंडेंट समीक्षा", "इंडेंट पुनरावलोकन", [
        fld("indent_ref", "text", "Indent Ref.", "इंडेंट संदर्भ", "इंडेंट संदर्भ"),
        fld("item_name", "text", "Item Name", "वस्तु का नाम", "वस्तूचे नाव"),
        fld("quantity", "number", "Quantity", "मात्रा", "प्रमाण", validation={"min": 0}),
        fld("vendor", "text", "Vendor", "विक्रेता", "विक्रेता"),
        fld("expected_date", "datetime", "Expected Date", "अपेक्षित तिथि", "अपेक्षित तारीख"),
    ]),
    ("SECURITY", "gate_entry", "Gate Entry", "गेट एंट्री", "गेट नोंद", [
        fld("entry_type", "select", "Entry Type", "एंट्री प्रकार", "नोंद प्रकार", options=["visitor", "vehicle", "material_out"]),
        fld("person_or_plate", "text", "Person / Vehicle Plate", "व्यक्ति / वाहन नंबर", "व्यक्ती / वाहन क्रमांक", ai_hook="anpr"),
        fld("id_photo", "photo", "ID Photo", "पहचान फोटो", "ओळख फोटो"),
        fld("purpose", "text", "Purpose", "उद्देश्य", "हेतू"),
    ]),
    ("AGRICULTURE", "field_visit", "Field Visit", "क्षेत्र भ्रमण", "शेत भेट", [
        fld("village", "text", "Village", "गांव", "गाव"),
        fld("farmer_name", "text", "Farmer Name", "किसान का नाम", "शेतकऱ्याचे नाव"),
        fld("plot_gps", "gps_point", "Plot GPS", "प्लॉट जीपीएस", "प्लॉट जीपीएस"),
        fld("crop_stage", "select", "Crop Stage", "फसल अवस्था", "पीक अवस्था", options=["germination", "tillering", "grand_growth", "maturity"]),
        fld("pest_photo", "photo", "Pest Photo", "कीट फोटो", "कीड फोटो", required=False),
        fld("notes", "text", "Notes", "नोट्स", "टिपा", required=False),
    ]),
    ("ACCOUNTS", "payment_note", "Payment Note", "भुगतान नोट", "देयक नोंद", [
        fld("farmer_or_vendor", "text", "Farmer / Vendor", "किसान / विक्रेता", "शेतकरी / विक्रेता"),
        fld("amount", "number", "Amount (₹)", "राशि (₹)", "रक्कम (₹)", validation={"min": 0}),
        fld("payment_type", "select", "Payment Type", "भुगतान प्रकार", "देयक प्रकार", options=["cane", "vendor", "salary_advance"]),
        fld("reference_no", "text", "Reference No.", "संदर्भ संख्या", "संदर्भ क्रमांक"),
        fld("remarks", "text", "Remarks", "टिप्पणी", "शेरा", required=False),
    ]),
    ("ADMIN", "grievance", "Complaint", "शिकायत", "तक्रार", [
        fld("subject", "text", "Subject", "विषय", "विषय"),
        fld("description", "text", "Description", "विवरण", "वर्णन"),
        fld("photo", "photo", "Photo", "फोटो", "फोटो", required=False),
        fld("urgency", "select", "Urgency", "तात्कालिकता", "तातडी", options=["low", "normal", "high"]),
    ]),
    ("CIVIL", "repair_request", "Repair Request", "मरम्मत अनुरोध", "दुरुस्ती विनंती", [
        fld("location", "text", "Location", "स्थान", "ठिकाण"),
        fld("problem_photo", "photo", "Problem Photo", "समस्या फोटो", "समस्या फोटो"),
        fld("description", "text", "Description", "विवरण", "वर्णन"),
        fld("urgency", "select", "Urgency", "तात्कालिकता", "तातडी", options=["low", "normal", "monsoon_critical"]),
    ]),
    ("TIME_OFFICE", "ot_capture", "OT Capture", "ओटी कैप्चर", "ओटी नोंद", [
        fld("employee_emp_id", "text", "Employee ID", "कर्मचारी आईडी", "कर्मचारी क्रमांक"),
        fld("ot_hours", "number", "OT Hours", "ओटी घंटे", "ओटी तास", validation={"min": 0, "max": 24}),
        fld("reason", "text", "Reason", "कारण", "कारण"),
        fld("shift_code", "select", "Shift", "शिफ्ट", "शिफ्ट", options=["A", "B", "C", "GEN"]),
    ]),
]


async def seed():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    counts = {}
    async with sm() as session:
        # roles
        existing_roles = {r.code for r in (await session.execute(select(Role))).scalars()}
        for code, en, hi, mr, rank in ROLES:
            if code not in existing_roles:
                session.add(Role(code=code, label_en=en, label_hi=hi, label_mr=mr, rank=rank))
        await session.flush()
        counts["roles"] = len(ROLES)

        # departments
        existing_depts = {d.code for d in (await session.execute(select(Department))).scalars()}
        for code, en, hi, mr in DEPARTMENTS:
            if code not in existing_depts:
                session.add(Department(code=code, name_en=en, name_hi=hi, name_mr=mr, is_active=True))
        await session.flush()
        counts["departments"] = len(DEPARTMENTS)

        # shifts
        existing_shifts = {s.code for s in (await session.execute(select(Shift))).scalars()}
        for code, label, start, end in SHIFTS:
            if code not in existing_shifts:
                session.add(Shift(code=code, label=label, start_time=start, end_time=end))
        await session.flush()
        counts["shifts"] = len(SHIFTS)

        # settings singleton (placeholder coords — real ones set via PATCH /api/admin/settings)
        if (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none() is None:
            session.add(FactorySettings(factory_lat=19.0000, factory_lng=74.7000, radius_meters=500))
        counts["settings"] = 1

        # employees from CSV
        if not CSV_PATH.exists():
            raise SystemExit(f"seed_employees.csv not found at {CSV_PATH} — run scripts/generate_seed_csv.py")
        existing_emp = {e.emp_id for e in (await session.execute(select(Employee))).scalars()}
        new_employees = 0
        with open(CSV_PATH) as f:
            for row in csv.DictReader(f):
                emp_id = row["emp_id"].strip()
                if emp_id in existing_emp:
                    continue
                full_name = (row.get("full_name") or row.get("name") or "").strip()
                role_code = (row.get("role_code") or row.get("role") or "Worker").strip()
                phone = (row.get("phone") or "").strip()
                status = (row.get("phone_status") or "OK").strip().upper()
                bad_phone = status != "OK"
                eligible = (row.get("shift_swap_eligible") or "").strip().lower() in ("true", "yes", "1")
                session.add(
                    Employee(
                        emp_id=emp_id,
                        full_name=full_name,
                        phone=None if bad_phone or not phone else phone,
                        department_code=row["department_code"].strip(),
                        designation=(row.get("designation") or "").strip(),
                        role_code=role_code,
                        language_pref=(row.get("language_pref") or "mr").strip() or "mr",
                        shift_swap_eligible=eligible,
                        onboarding_status="seeded" if bad_phone else "approved",
                        is_active=True,
                    )
                )
                new_employees += 1
        await session.flush()
        counts["employees_new"] = new_employees

        all_employees = (await session.execute(select(Employee))).scalars().all()
        counts["employees_total"] = len(all_employees)

        # department managers (auto-assign from role=Manager rows, lowest emp_id wins
        # so the senior manager — e.g. Works Manager before Deputy Chief Engineers — is picked)
        dept_map = {d.code: d for d in (await session.execute(select(Department))).scalars()}
        managers_assigned = 0
        managers = sorted((e for e in all_employees if e.role_code == "Manager"), key=lambda e: e.emp_id)
        for emp in managers:
            dept = dept_map.get(emp.department_code)
            if dept is not None and dept.manager_employee_id is None:
                dept.manager_employee_id = emp.id
                managers_assigned += 1
        counts["managers_assigned"] = managers_assigned

        # baseline shift assignments
        assigned_ids = {
            a.employee_id
            for a in (
                await session.execute(select(ShiftAssignment).where(ShiftAssignment.source == "baseline"))
            ).scalars()
        }
        new_assignments = 0
        for emp in all_employees:
            if emp.id in assigned_ids:
                continue
            code = "A" if (emp.role_code == "Worker" and emp.department_code in SHIFT_A_DEPARTMENTS) else "GEN"
            session.add(
                ShiftAssignment(employee_id=emp.id, shift_code=code, effective_date=BASELINE_DATE, source="baseline")
            )
            new_assignments += 1
        counts["shift_assignments_new"] = new_assignments

        # 13 form definitions
        existing_forms = {
            (fd.department_code, fd.code)
            for fd in (await session.execute(select(FormDefinition))).scalars()
        }
        new_forms = 0
        for dept_code, code, en, hi, mr, fields in FORMS:
            if (dept_code, code) in existing_forms:
                continue
            session.add(
                FormDefinition(
                    department_code=dept_code, code=code,
                    title_en=en, title_hi=hi, title_mr=mr,
                    schema_json={"fields": fields},
                    version=1, is_active=True, requires_approval=True,
                    approval_role_code="Manager",
                )
            )
            new_forms += 1
        counts["form_definitions_new"] = new_forms

        await session.commit()
    await engine.dispose()
    print("Seed complete:", counts)


if __name__ == "__main__":
    asyncio.run(seed())
