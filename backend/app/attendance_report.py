"""Daily department-wise attendance report (2026-06).

Builds the data for a single day (present / absent / flagged / auto-punch-out per
department with name lists + per-row detail) and renders it to a clean, printable
trilingual (Marathi-first / Hindi / English) PDF and an Excel workbook. Reuses the
Devanagari fpdf2 setup from app.report (text shaping ON).
"""
from __future__ import annotations

import io
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendance, Department, Employee
from app.report import ReportPDF, _section, _table
from app.shift_logic import IST

# plain-language flag reasons (Marathi + English) — meaningful to the reader, never a code.
REASON_LABELS: dict[str, dict[str, str]] = {
    "face_mismatch": {"en": "Face did not match", "mr": "चेहरा जुळला नाही"},
    "reference_bootstrap": {"en": "First selfie — needs confirmation", "mr": "पहिला सेल्फी — पुष्टी हवी"},
    "gps_missing": {"en": "No GPS location captured", "mr": "GPS स्थान मिळाले नाही"},
    "field_no_gps": {"en": "Field punch without GPS", "mr": "फील्ड पंच पण GPS नाही"},
    "no_beacon_gps_only": {"en": "No beacon detected (GPS only)", "mr": "बीकन मिळाला नाही (फक्त GPS)"},
    "no_beacon_no_gps": {"en": "No beacon and no GPS", "mr": "बीकन नाही व GPS नाही"},
    "no_punch_out": {"en": "No punch-out recorded", "mr": "पंच-आउट नोंदले नाही"},
}


def plain_reason(reason: str | None, lang: str = "en") -> str:
    if not reason:
        return ""
    if reason.startswith("outside_geofence"):
        m = reason[reason.find("(") + 1: reason.find(")")] if "(" in reason else ""
        return (f"कारखान्याबाहेर ({m})" if lang == "mr" else f"Outside factory ({m})")
    if reason.startswith("gps_inaccurate"):
        m = reason[reason.find("(") + 1: reason.find(")")] if "(" in reason else ""
        return (f"GPS अचूक नाही ({m})" if lang == "mr" else f"GPS not accurate ({m})")
    label = REASON_LABELS.get(reason)
    if label:
        return label.get(lang, label["en"])
    return reason


def path_label(a: Attendance, lang: str = "en") -> str:
    """How the punch was verified + where, as a short human string."""
    if a.verification_path == "beacon" and a.ble_zone:
        return (f"बीकन · {a.ble_zone}" if lang == "mr" else f"Beacon · {a.ble_zone}")
    where = a.geo_address or (
        f"{a.gps_lat:.5f}, {a.gps_lng:.5f}" if a.gps_lat is not None and a.gps_lng is not None else ""
    )
    if a.verification_path == "field":
        return (f"फील्ड · {where}" if lang == "mr" else f"Field · {where}") if where else ("फील्ड" if lang == "mr" else "Field")
    if a.verification_path == "gps":
        return (f"स्थान · {where}" if lang == "mr" else f"Location · {where}") if where else ("स्थान" if lang == "mr" else "Location")
    return where


def _hhmm(dt) -> str:
    return dt.astimezone(IST).strftime("%H:%M") if dt else "—"


def _hours(a: Attendance) -> str:
    if a.punch_in_at and a.punch_out_at:
        h = (a.punch_out_at - a.punch_in_at).total_seconds() / 3600
        return f"{h:.1f}"
    return "—"


async def build_daily_attendance(session: AsyncSession, target: date_type, is_demo: bool) -> dict:
    """Per-department present/absent/flagged/auto counts + name lists + present rows."""
    depts = (
        await session.execute(
            select(Department).where(Department.is_active.is_(True)).order_by(Department.code)
        )
    ).scalars().all()
    dept_by_code = {d.code: d for d in depts}

    # active workforce (for absentee computation)
    emps = (
        await session.execute(
            select(Employee).where(
                Employee.is_active.is_(True),
                Employee.is_demo == is_demo,
                Employee.department_code.isnot(None),
            )
        )
    ).scalars().all()
    emp_by_dept: dict[str, list[Employee]] = {}
    for e in emps:
        emp_by_dept.setdefault(e.department_code, []).append(e)

    rows = (
        await session.execute(
            select(Attendance, Employee)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(Attendance.date == target, Attendance.is_demo == is_demo)
            .order_by(Employee.department_code, Attendance.punch_in_at)
        )
    ).all()
    att_by_dept: dict[str, list[tuple[Attendance, Employee]]] = {}
    present_emp_ids: dict[str, set] = {}
    for a, e in rows:
        att_by_dept.setdefault(e.department_code, []).append((a, e))
        present_emp_ids.setdefault(e.department_code, set()).add(e.id)

    departments = []
    totals = {"present": 0, "absent": 0, "flagged": 0, "auto_punch_out": 0, "late": 0}
    for code in sorted(set(list(emp_by_dept.keys()) + list(att_by_dept.keys()))):
        d = dept_by_code.get(code)
        present_rows = []
        flagged = auto = late = 0
        for a, e in att_by_dept.get(code, []):
            is_auto = a.punch_out_source == "auto"
            is_flagged = a.verification_level == "flagged" or a.flagged_reason == "no_punch_out"
            if is_flagged:
                flagged += 1
            if is_auto:
                auto += 1
            if a.is_late:
                late += 1
            present_rows.append({
                "attendance_id": str(a.id),
                "name": e.full_name,
                "emp_id": e.emp_id,
                "designation": e.designation or "",
                "punch_in": _hhmm(a.punch_in_at),
                "punch_out": _hhmm(a.punch_out_at),
                "hours": _hours(a),
                "verification_level": a.verification_level,
                "verification_path": a.verification_path,
                "zone": a.ble_zone,
                "address": a.geo_address,
                "gps_lat": a.gps_lat,
                "gps_lng": a.gps_lng,
                "gps_accuracy": a.gps_accuracy,
                "geo_distance_m": a.geo_distance_m,
                "inside_geofence": a.gps_verified,
                "is_field": bool(d and d.geofence_exempt),
                "auto_punch_out": is_auto,
                "is_late": a.is_late,
                "flagged_reason": a.flagged_reason,
                "path_en": path_label(a, "en"),
                "path_mr": path_label(a, "mr"),
                "reason_en": plain_reason(a.flagged_reason, "en"),
                "reason_mr": plain_reason(a.flagged_reason, "mr"),
            })
        present_ids = present_emp_ids.get(code, set())
        absent = [
            {"name": e.full_name, "emp_id": e.emp_id, "designation": e.designation or ""}
            for e in emp_by_dept.get(code, []) if e.id not in present_ids
        ]
        p = len(present_rows)
        totals["present"] += p
        totals["absent"] += len(absent)
        totals["flagged"] += flagged
        totals["auto_punch_out"] += auto
        totals["late"] += late
        departments.append({
            "code": code,
            "name_en": d.name_en if d else code,
            "name_mr": d.name_mr if d else code,
            "is_field": bool(d and d.geofence_exempt),
            "present": p,
            "absent": len(absent),
            "flagged": flagged,
            "auto_punch_out": auto,
            "late": late,
            "present_rows": present_rows,
            "absent_names": absent,
        })
    return {"date": target.isoformat(), "totals": totals, "departments": departments}


# ---------------- PDF (bilingual: Marathi / English) ----------------

def _bi(mr: str, en: str) -> str:
    return f"{mr} / {en}"


def _tri(mr: str, hi: str, en: str) -> str:
    """Trilingual label, Marathi first. Collapses to 'mr / en' when Marathi==Hindi."""
    return f"{mr} / {en}" if mr == hi else f"{mr} / {hi} / {en}"


def render_attendance_pdf(data: dict) -> bytes:
    pdf = ReportPDF()
    pdf.add_page()
    pdf.set_font("NotoDeva", "B", 17)
    pdf.set_text_color(11, 79, 108)
    pdf.cell(0, 11, _tri("दैनिक हजेरी अहवाल", "दैनिक उपस्थिति रिपोर्ट", "Daily Attendance Report"))
    pdf.ln(11)
    pdf.set_font("NotoDeva", "", 11)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 8, f"{_bi('दिनांक', 'Date')}: {data['date']}")
    pdf.ln(11)

    t = data["totals"]
    _section(pdf, _tri("एकूण", "कुल", "Summary"))
    _table(
        pdf,
        [_tri("उपस्थित", "उपस्थित", "Present"), _tri("अनुपस्थित", "अनुपस्थित", "Absent"),
         _tri("चिन्हांकित", "चिह्नित", "Flagged"),
         _tri("स्वयं पंच-आउट", "स्वतः पंच-आउट", "Auto out"), _tri("उशिरा", "देर", "Late")],
        [[t["present"], t["absent"], t["flagged"], t["auto_punch_out"], t["late"]]],
        [40, 40, 40, 40, 30],
    )

    _section(pdf, _bi("विभागानुसार", "By Department"))
    _table(
        pdf,
        [_bi("विभाग", "Department"), _bi("उप.", "Pres"), _bi("अनुप.", "Abs"),
         _bi("चिन्ह.", "Flag"), _bi("स्वयं", "Auto")],
        [[_bi(d["name_mr"], d["name_en"]) + (" ⛳" if d["is_field"] else ""),
          d["present"], d["absent"], d["flagged"], d["auto_punch_out"]]
         for d in data["departments"]],
        [95, 25, 25, 25, 20],
    )

    for d in data["departments"]:
        if not d["present_rows"] and not d["absent_names"]:
            continue
        _section(pdf, _bi(d["name_mr"], d["name_en"]) + (" — ⛳ " + _bi("फील्ड", "Field") if d["is_field"] else ""))
        if d["present_rows"]:
            pdf.set_font("NotoDeva", "B", 9)
            pdf.set_text_color(40, 37, 29)
            pdf.cell(0, 7, _bi("उपस्थित", "Present"))
            pdf.ln(7)
            _table(
                pdf,
                [_bi("नाव", "Name"), _bi("ओळख", "ID"), _bi("आत", "In"),
                 _bi("बाहेर", "Out"), _bi("तास", "Hrs"), _bi("पडताळणी / स्थिती", "Verify / Status")],
                [[
                    r["name"], r["emp_id"], r["punch_in"], r["punch_out"], r["hours"],
                    (r["reason_mr"] or "—") if r["verification_level"] == "flagged"
                    else (r["path_mr"] or ("स्वयं बाहेर" if r["auto_punch_out"] else "ठीक")),
                ] for r in d["present_rows"]],
                [45, 22, 16, 16, 14, 77],
            )
        if d["absent_names"]:
            pdf.set_font("NotoDeva", "B", 9)
            pdf.set_text_color(176, 58, 58)
            pdf.cell(0, 7, f"{_bi('अनुपस्थित', 'Absent')} ({len(d['absent_names'])})")
            pdf.ln(7)
            pdf.set_font("NotoDeva", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.multi_cell(0, 6, ", ".join(f"{a['name']} ({a['emp_id']})" for a in d["absent_names"]))
            pdf.ln(3)

    pdf.set_font("NotoDeva", "", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 6, f"{_bi('होगो प्लस द्वारे तयार', 'Generated by Hogo Plus')} · {date_type.today().isoformat()}")
    return bytes(pdf.output())


# ---------------- Excel (openpyxl) ----------------

def render_attendance_xlsx(data: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="0B4F6C")
    head_font = Font(color="FFFFFF", bold=True)

    def _style_header(ws, ncols: int) -> None:
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center")

    def _autosize(ws, widths: list[int]) -> None:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    ws = wb.active
    ws.title = "Summary"
    ws.append([f"दैनिक हजेरी / Daily Attendance — {data['date']}"])
    ws.append([])
    ws.append([
        "विभाग / Department", "फील्ड / Field", "उपस्थित / Present", "अनुपस्थित / Absent",
        "चिन्हांकित / Flagged", "स्वयं बाहेर / Auto out", "उशिरा / Late",
    ])
    for c in range(1, 8):
        cell = ws.cell(row=3, column=c)
        cell.fill = head_fill
        cell.font = head_font
    for d in data["departments"]:
        ws.append([
            f"{d['name_mr']} / {d['name_en']}", "⛳" if d["is_field"] else "",
            d["present"], d["absent"], d["flagged"], d["auto_punch_out"], d["late"],
        ])
    t = data["totals"]
    ws.append(["एकूण / Total", "", t["present"], t["absent"], t["flagged"], t["auto_punch_out"], t["late"]])
    _autosize(ws, [34, 10, 16, 16, 16, 16, 10])

    det = wb.create_sheet("Present")
    det.append([
        "विभाग / Dept", "नाव / Name", "ओळख / ID", "पदनाम / Designation",
        "आत / In", "बाहेर / Out", "तास / Hours", "पडताळणी / Verification",
        "आत/बाहेर / In-Geofence", "अचूकता(m) / Accuracy", "स्थिती / Status",
    ])
    _style_header(det, 11)
    for d in data["departments"]:
        for r in d["present_rows"]:
            status = (r["reason_en"] or "Flagged") if r["verification_level"] == "flagged" else (
                "Auto punch-out" if r["auto_punch_out"] else r["verification_level"]
            )
            det.append([
                f"{d['name_mr']} / {d['name_en']}", r["name"], r["emp_id"], r["designation"],
                r["punch_in"], r["punch_out"], r["hours"], r["path_en"],
                ("Field" if r["is_field"] else ("Inside" if r["inside_geofence"] else "Outside")),
                (round(r["gps_accuracy"]) if r["gps_accuracy"] is not None else ""),
                status,
            ])
    _autosize(det, [22, 26, 12, 24, 8, 8, 8, 40, 16, 14, 22])

    ab = wb.create_sheet("Absent")
    ab.append(["विभाग / Dept", "नाव / Name", "ओळख / ID", "पदनाम / Designation"])
    _style_header(ab, 4)
    for d in data["departments"]:
        for a in d["absent_names"]:
            ab.append([f"{d['name_mr']} / {d['name_en']}", a["name"], a["emp_id"], a["designation"]])
    _autosize(ab, [22, 26, 12, 24])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
