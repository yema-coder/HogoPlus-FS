"""Prompt 14: seed permanent demo showcase data (is_demo=true AND is_demo_seed=true).

Re-runnable: wipes ALL existing demo data rows (seed + judge-created) first,
then seeds fresh showcase content with timestamps inside the last 72h:
  - 1-2 form submissions per department in mixed states (approved / pending /
    rejected), PURCHASE approved indent with approval trail, CANE_YARD weighment
    with detected plate MH16AB1234
  - 7 incidents across departments (submitted / seen / in_progress / resolved
    with photo / escalated), synthesized photos uploaded under demo-seed-* keys
  - 3 days of attendance for 6 demo workers (one flagged for the TO queue demo)
  - matching notifications for demo managers / Demo CGM

Run: cd /app/backend && python scripts/seed_demo_showcase.py
"""
import asyncio
import io
import random
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import (
    Attendance,
    Department,
    Employee,
    FormDefinition,
    FormSubmission,
    Incident,
    IncidentTimeline,
    Notification,
    ShiftAssignment,
    ShiftSwapRequest,
)
from app.notify import T as NOTIF_TEMPLATES

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(timezone.utc)
rng = random.Random(1414)

DEPTS = [
    "ACCOUNTS", "ADMIN", "AGRICULTURE", "CANE_YARD", "CIVIL", "DISTILLERY",
    "ENGINEERING", "GODOWN", "PRODUCTION", "PURCHASE", "SECURITY", "STORE", "TIME_OFFICE",
]

SAMPLE_TEXT = {
    "remarks": "सर्व काही व्यवस्थित / All normal",
    "notes": "पुढील आठवड्यात पुन्हा भेट / Revisit next week",
    "farmer_code": "F-2381",
    "farmer_name": "Ramesh Pawar",
    "village": "Shrigonda",
    "truck_plate": "MH16AB1234",
    "vehicle_plate": "MH12KP4821",
    "person_or_plate": "MH16AB1234",
    "item_name": "Bearing 6205-2RS",
    "indent_ref": "IND-2024-0871",
    "vendor": "Kirloskar Traders, Ahmednagar",
    "asset_name": "Mill Roller #2",
    "problem_description": "रोलर मध्ये आवाज येत आहे / Abnormal noise from roller",
    "parts_needed": "Bearing + coupling",
    "tank_no": "T-04",
    "purpose": "Vendor material delivery",
}


def _fill_data(schema: dict) -> dict:
    data = {}
    for f in schema.get("fields", []):
        t, key = f.get("type"), f.get("key")
        if t == "text":
            data[key] = SAMPLE_TEXT.get(key, "Demo sample entry")
        elif t == "number":
            v = f.get("validation") or {}
            lo, hi = v.get("min", 0) or 0, v.get("max", 100) or 100
            data[key] = round((lo + hi) / 2, 1)
        elif t == "select":
            opts = f.get("options") or []
            data[key] = opts[0] if opts else "n/a"
        elif t == "toggle":
            data[key] = True
        elif t == "datetime":
            data[key] = (NOW + timedelta(days=3)).date().isoformat()
        elif t == "gps_point":
            data[key] = {"lat": 19.001, "lng": 74.702}
        # photo fields → handled via submission.photos
    return data


def _make_jpeg(label: str, color: tuple) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), color)
    d = ImageDraw.Draw(img)
    d.rectangle([16, 16, 624, 464], outline=(255, 255, 255), width=4)
    d.text((40, 210), label, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _save_seed_image(storage, label: str) -> str:
    from app.storage import S3Storage

    key = f"demo-seed-{uuid.uuid4().hex}.jpg"
    body = _make_jpeg(label, (rng.randint(30, 160), rng.randint(30, 160), rng.randint(30, 160)))
    if isinstance(storage, S3Storage):
        storage.client.put_object(
            Bucket=storage.bucket, Key=key, Body=body, ContentType="image/jpeg"
        )
    else:
        (storage.base / key).write_bytes(body)
    return key


def _make_wav(seconds: int = 4) -> bytes:
    """Soft two-tone hum with fade — a playable placeholder 'voice note'."""
    import math
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n = 16000 * seconds
        frames = bytearray()
        for i in range(n):
            env = min(i, n - i, 3000) / 3000
            wobble = 1 + 0.15 * math.sin(2 * math.pi * 2.1 * i / 16000)
            v = 0.22 * math.sin(2 * math.pi * 170 * wobble * i / 16000)
            v += 0.12 * math.sin(2 * math.pi * 260 * i / 16000)
            frames += struct.pack("<h", int(v * env * 32767))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _save_seed_audio(storage) -> str:
    from app.storage import S3Storage

    key = f"demo-seed-{uuid.uuid4().hex}.wav"
    body = _make_wav()
    if isinstance(storage, S3Storage):
        storage.client.put_object(
            Bucket=storage.bucket, Key=key, Body=body, ContentType="audio/wav"
        )
    else:
        (storage.base / key).write_bytes(body)
    return key


def _title(dept: str) -> str:
    return dept.replace("_", " ").title()


def _ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


async def main() -> None:
    from app.demo_cleanup import run_demo_cleanup
    from app.storage import get_storage

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    storage = get_storage()

    async with sm() as session:
        # wipe ALL existing demo data (seed included) so re-runs stay clean
        wiped = await run_demo_cleanup(
            session, include_seed=True, older_than_minutes=None, delete_media=True
        )
        print(f"wiped existing demo data: {wiped}")

        demo_emps = (
            await session.execute(select(Employee).where(Employee.is_demo.is_(True)))
        ).scalars().all()
        workers = {
            e.department_code: e
            for e in demo_emps
            if e.role_code == "Worker" and not e.full_name.endswith("2")
        }
        managers = {e.department_code: e for e in demo_emps if e.role_code == "Manager"}
        cgm = next((e for e in demo_emps if e.role_code == "CGM"), None)
        if len(workers) < 13 or len(managers) < 13 or cgm is None:
            raise SystemExit("Demo cast missing — run scripts/seed_demo_cast.py first")

        # ---------- extra cast: second Workers (swap partners) + 1 pending registration ----------
        async def ensure_employee(emp_id, name, phone, dept, status="approved"):
            emp = (
                await session.execute(select(Employee).where(Employee.phone == phone))
            ).scalar_one_or_none()
            if emp is None:
                emp = Employee(
                    emp_id=emp_id, full_name=name, phone=phone, department_code=dept,
                    designation=name, role_code="Worker", language_pref="en",
                    shift_swap_eligible=True, onboarding_status=status,
                    is_active=True, is_demo=True,
                )
                session.add(emp)
                await session.flush()
                session.add(ShiftAssignment(
                    employee_id=emp.id, shift_code="GEN",
                    effective_date=datetime(2025, 1, 1).date(), source="baseline",
                ))
            else:
                emp.onboarding_status = status  # reset (judge may have approved the pending one)
            return emp

        workers2 = {}
        for i, dept in enumerate(["SECURITY", "PRODUCTION", "ENGINEERING", "STORE"], start=21):
            workers2[dept] = await ensure_employee(
                f"D{i:03d}", f"Demo {_title(dept)} Worker 2", f"+91{9000000000 + i}", dept
            )
        pending_reg = await ensure_employee(
            "D700", "Demo Pending Worker", "+919000000700", "PRODUCTION",
            status="pending_approval",
        )

        forms = {}
        for d in DEPTS:
            fdefs = (
                await session.execute(
                    select(FormDefinition).where(
                        FormDefinition.department_code == d, FormDefinition.is_active.is_(True)
                    ).order_by(FormDefinition.code)
                )
            ).scalars().all()
            forms[d] = fdefs

        dept_names = {
            d.code: d.name_en
            for d in (await session.execute(select(Department))).scalars().all()
        }

        def notif(recipient_id, type_, body_text, entity_type, entity_id, created_at):
            t = NOTIF_TEMPLATES.get(type_, {"title": {"en": type_, "hi": type_, "mr": type_}})
            session.add(Notification(
                recipient_id=recipient_id, type=type_,
                title_en=t["title"]["en"], title_hi=t["title"]["hi"], title_mr=t["title"]["mr"],
                body_en=body_text, body_hi=body_text, body_mr=body_text,
                entity_type=entity_type, entity_id=str(entity_id),
                is_demo=True, is_demo_seed=True, created_at=created_at,
            ))

        # ---------- form submissions: 1-2 per department, mixed states ----------
        # (dept, form_index, status, extras)
        plan = [
            ("PURCHASE", 0, "approved", {}),           # approved indent w/ full trail
            ("STORE", 0, "submitted", {}),             # material issue PENDING
            ("ACCOUNTS", 0, "approved", {}),           # payment/accounts note APPROVED
            ("CANE_YARD", 0, "approved", {"plates": ["MH16AB1234"], "photo": "Weighbridge 12480 kg"}),
            ("ENGINEERING", 0, "rejected", {"reason": "Photo aspaṣṭa āhe — please attach a clear before-photo of the roller."}),
            ("ENGINEERING", 0, "approved", {"photo": "Job card — after repair"}),
            ("PRODUCTION", 0, "submitted", {"photo": "Pan gauge 21.4 brix"}),
            ("SECURITY", 0, "approved", {"photo": "Gate pass — vendor entry"}),
            ("DISTILLERY", 0, "submitted", {"photo": "Tank T-04 gauge"}),
            ("ADMIN", 0, "submitted", {}),
            ("AGRICULTURE", 0, "approved", {}),
            ("CIVIL", 0, "submitted", {}),
            ("GODOWN", 0, "approved", {"plates": ["MH12KP4821"]}),
            ("TIME_OFFICE", 0, "submitted", {}),
        ]
        n_subs = 0
        for dept, idx, status, extras in plan:
            fdefs = forms.get(dept) or []
            if idx >= len(fdefs):
                continue
            fdef = fdefs[idx]
            created = _ago(rng.uniform(4, 68))
            photos = []
            if extras.get("photo"):
                photos.append(_save_seed_image(storage, extras["photo"]))
            sub = FormSubmission(
                form_definition_id=fdef.id, form_version=fdef.version,
                submitted_by=workers[dept].id, department_code=dept,
                data_json=_fill_data(fdef.schema_json), photos=photos,
                detected_plates=extras.get("plates"),
                gps_lat=19.001, gps_lng=74.702,
                status=status, is_demo=True, is_demo_seed=True,
                created_at=created, updated_at=created,
            )
            if status in ("approved", "rejected"):
                sub.approver_id = managers[dept].id
                sub.approved_at = created + timedelta(hours=rng.uniform(0.5, 3))
                if status == "rejected":
                    sub.rejection_reason = extras.get("reason", "Incomplete details")
            session.add(sub)
            await session.flush()
            if status == "submitted":
                notif(managers[dept].id, "submission_pending",
                      f"{fdef.title_en} — {workers[dept].full_name}",
                      "form_submission", sub.id, created)
            else:
                notif(workers[dept].id, "submission_decided",
                      "Approved" if status == "approved" else f"Rejected: {sub.rejection_reason}",
                      "form_submission", sub.id, sub.approved_at)
            n_subs += 1

        # ---------- incidents: EVERY department gets 1-2 open ones, varied states ----------
        # keys: dept, category, status, severity, desc, label, voice, plate
        inc_plan = [
            {"dept": "ACCOUNTS", "category": "other", "status": "submitted", "severity": "normal",
             "desc": "प्रिंटर खराब आहे — पगार शीट निघत नाही / ledger mismatch in cash book", "label": "Printer error screen"},
            {"dept": "ADMIN", "category": "other", "status": "submitted", "severity": "normal",
             "desc": "Meeting hall AC गळत आहे — फायली भिजण्याचा धोका", "label": "AC water leak"},
            {"dept": "AGRICULTURE", "category": "other", "status": "in_progress", "severity": "normal",
             "desc": "Nursery पंप वारंवार बंद पडतो — रोपांना पाणी देता येत नाही", "label": "Nursery pump"},
            {"dept": "CANE_YARD", "category": "machine_breakdown", "status": "submitted", "severity": "normal",
             "desc": "Weighbridge display फ्लिकर होत आहे — वजन नीट दिसत नाही", "label": "Weighbridge display + truck MH16AB1234",
             "voice": True, "plate": "MH16AB1234"},
            {"dept": "CANE_YARD", "category": "safety", "status": "seen", "severity": "high",
             "desc": "ऊस ट्रक चुकीच्या रांगेत — weighbridge जवळ अपघाताचा धोका", "label": "Truck queue hazard"},
            {"dept": "CIVIL", "category": "water_leakage", "status": "submitted", "severity": "normal",
             "desc": "गोदामाच्या छताला गळती — पावसात पोती भिजतील / godown roof leakage", "label": "Roof leakage"},
            {"dept": "DISTILLERY", "category": "machine_breakdown", "status": "in_progress", "severity": "normal",
             "desc": "Spent wash line चोक झाली आहे — flow पूर्ण बंद", "label": "Spent wash line choke"},
            {"dept": "DISTILLERY", "category": "fire", "status": "escalated", "severity": "critical",
             "desc": "Boiler section जवळ धूर दिसला — तातडीने तपासा", "label": "Smoke near boiler"},
            {"dept": "ENGINEERING", "category": "machine_breakdown", "status": "in_progress", "severity": "high",
             "desc": "Mill bearing गरम होत आहे — तापमान ८५°C च्या वर / mill bearing overheating", "label": "Hot bearing IR reading",
             "voice": True},
            {"dept": "ENGINEERING", "category": "electrical", "status": "resolved", "severity": "normal",
             "desc": "Panel room MCB वारंवार ट्रिप होत होता", "label": "MCB panel",
             "resolution": "MCB बदलला — लोड टेस्ट ओके / MCB replaced, load tested OK"},
            {"dept": "GODOWN", "category": "safety", "status": "submitted", "severity": "normal",
             "desc": "पोत्यांची थप्पी झुकलेली आहे — bag stacking unsafe", "label": "Bag stack leaning"},
            {"dept": "PRODUCTION", "category": "machine_breakdown", "status": "submitted", "severity": "normal",
             "desc": "Pan section steam pressure कमी आहे — batch उशिरा होईल", "label": "Steam pressure gauge",
             "voice": True},
            {"dept": "PURCHASE", "category": "other", "status": "submitted", "severity": "normal",
             "desc": "Urgent indent चे material अजून आले नाही — vendor उत्तर देत नाही", "label": "Pending indent file"},
            {"dept": "SECURITY", "category": "machine_breakdown", "status": "resolved", "severity": "normal",
             "desc": "Gate 1 barrier जाम झाला होता — वाहने अडकली होती", "label": "Gate barrier jam",
             "resolution": "Barrier motor greasing केले — आता व्यवस्थित चालतो"},
            {"dept": "SECURITY", "category": "security", "status": "submitted", "severity": "normal",
             "desc": "CCTV camera क्र. ६ बंद आहे — मागचे गेट दिसत नाही", "label": "CCTV cam 6 offline"},
            {"dept": "STORE", "category": "safety", "status": "submitted", "severity": "high",
             "desc": "Rack क्र. १२ वाकला आहे — कोसळण्याचा धोका / rack collapse risk", "label": "Bent rack 12"},
            {"dept": "TIME_OFFICE", "category": "other", "status": "submitted", "severity": "normal",
             "desc": "Biometric machine बंद आहे — कामगारांची रांग लागली आहे", "label": "Biometric machine down"},
        ]
        n_incs = 0
        for spec in inc_plan:
            dept, category = spec["dept"], spec["category"]
            status, severity = spec["status"], spec["severity"]
            created = _ago(rng.uniform(4, 70))
            photo_key = _save_seed_image(storage, spec["label"])
            inc = Incident(
                reported_by=workers[dept].id, department_code=dept, category=category,
                photo_key=photo_key,
                voice_note_key=_save_seed_audio(storage) if spec.get("voice") else None,
                detected_plate=spec.get("plate"),
                gps_lat=19.001, gps_lng=74.702,
                address_text="Hogo Sugar Factory premises",
                description=spec["desc"], status=status, severity=severity,
                severity_reason="Seeded showcase incident",
                assigned_manager_id=managers[dept].id,
                ai_confirmed_by="explicit", is_demo=True, is_demo_seed=True,
                created_at=created, updated_at=created,
            )
            if status == "resolved":
                inc.resolved_at = created + timedelta(hours=2)
                inc.resolution_note = spec.get("resolution", "Resolved on site.")
                inc.resolution_photo_key = _save_seed_image(storage, f"Resolved: {spec['label']}")
            if status == "escalated":
                inc.escalated_to = cgm.id
                inc.escalated_at = created + timedelta(hours=1)
            session.add(inc)
            await session.flush()
            session.add(IncidentTimeline(
                incident_id=inc.id, actor_id=workers[dept].id, event="created",
                detail_json={"category": category, "severity": severity}, created_at=created,
            ))
            if status in ("seen", "in_progress", "resolved"):
                session.add(IncidentTimeline(
                    incident_id=inc.id, actor_id=managers[dept].id, event="status_change",
                    detail_json={"from": "submitted", "to": status},
                    created_at=created + timedelta(hours=1),
                ))
            if status == "escalated":
                session.add(IncidentTimeline(
                    incident_id=inc.id, actor_id=None, event="escalated",
                    detail_json={"escalated_to": str(cgm.id), "level": "CGM"},
                    created_at=inc.escalated_at,
                ))
                notif(cgm.id, "incident_escalated", f"{category} — {dept_names.get(dept, dept)}",
                      "incident", inc.id, inc.escalated_at)
            if severity == "critical":
                notif(cgm.id, "incident_critical", f"{category} — {dept_names.get(dept, dept)}",
                      "incident", inc.id, created)
            notif(managers[dept].id, "incident_assigned",
                  f"{category} — {dept_names.get(dept, dept)}", "incident", inc.id, created)
            n_incs += 1

        # ---------- shift swaps: pending_target ×2, pending_manager ×2, approved ×1 ----------
        swap_plan = [
            ("SECURITY", "pending_target", 3, "गावी लग्नाला जायचे आहे / family wedding in village"),
            ("PRODUCTION", "pending_target", 4, "Doctor appointment — दवाखान्यात जायचे आहे"),
            ("ENGINEERING", "pending_manager", 3, "मुलाच्या शाळेत पालक सभा आहे"),
            ("STORE", "pending_manager", 5, "Panchayat कामासाठी सुट्टी हवी आहे"),
            ("SECURITY", "approved", 2, "Night shift adjust करायची आहे — परस्पर सहमती"),
        ]
        n_swaps = 0
        today_local = NOW.astimezone(IST).date()
        for dept, status, days_ahead, reason in swap_plan:
            requester = workers[dept] if status != "approved" else workers2[dept]
            target = workers2[dept] if status != "approved" else workers[dept]
            created = _ago(rng.uniform(3, 30))
            swap = ShiftSwapRequest(
                requester_id=requester.id, target_id=target.id,
                swap_date=today_local + timedelta(days=days_ahead),
                status=status, reason=reason,
                is_demo=True, is_demo_seed=True,
                created_at=created, updated_at=created,
            )
            if status in ("pending_manager", "approved"):
                swap.target_responded_at = created + timedelta(hours=1)
            if status == "approved":
                swap.manager_id = managers[dept].id
                swap.manager_responded_at = created + timedelta(hours=3)
            session.add(swap)
            await session.flush()
            if status == "pending_target":
                notif(target.id, "swap_request",
                      f"{requester.full_name} → {swap.swap_date.isoformat()}: {reason}",
                      "shift_swap", swap.id, created)
            elif status == "pending_manager":
                notif(managers[dept].id, "swap_manager_pending",
                      f"{requester.full_name} ⇄ {target.full_name} — {swap.swap_date.isoformat()}",
                      "shift_swap", swap.id, swap.target_responded_at)
            else:
                notif(requester.id, "swap_decided",
                      f"Approved — {swap.swap_date.isoformat()}", "shift_swap", swap.id,
                      swap.manager_responded_at)
            n_swaps += 1

        # ---------- pending registration notifications (record itself is the employee) ----------
        notif(managers["TIME_OFFICE"].id, "registration_pending",
              f"{pending_reg.full_name} — Production", "employee", pending_reg.id, _ago(6))
        notif(cgm.id, "registration_pending",
              f"{pending_reg.full_name} — Production", "employee", pending_reg.id, _ago(6))

        # ---------- attendance: last 3 days for 6 demo workers ----------
        att_depts = ["ACCOUNTS", "PRODUCTION", "ENGINEERING", "SECURITY", "STORE", "TIME_OFFICE"]
        n_atts = 0
        today_ist = NOW.astimezone(IST).date()
        for day_offset in (1, 2, 3):
            day = today_ist - timedelta(days=day_offset)
            for j, dept in enumerate(att_depts):
                w = workers[dept]
                punch_in = datetime.combine(day, time(8, 50 + j), tzinfo=IST).astimezone(timezone.utc)
                flagged = day_offset == 1 and dept == "PRODUCTION"  # one row for the TO queue demo
                session.add(Attendance(
                    employee_id=w.id, date=day, punch_in_at=punch_in,
                    punch_out_at=punch_in + timedelta(hours=8, minutes=35),
                    gps_lat=19.001 if not flagged else 19.02, gps_lng=74.702,
                    gps_verified=not flagged,
                    selfie_key=_save_seed_image(storage, f"Selfie {w.full_name} {day}"),
                    verification_level="flagged" if flagged else "verified",
                    flagged_reason="outside_geofence(742m)" if flagged else None,
                    shift_code="GEN", is_late=False,
                    is_demo=True, is_demo_seed=True,
                    created_at=punch_in, updated_at=punch_in,
                ))
                n_atts += 1

        await session.commit()
    await engine.dispose()
    print(
        f"Showcase seeded: {n_subs} form submissions, {n_incs} incidents, "
        f"{n_swaps} shift swaps, {n_atts} attendance rows, 1 pending registration"
    )


if __name__ == "__main__":
    asyncio.run(main())
