"""One-time roster import — AGRICULTURE dept 2026-27 ("shetki vibhag" Excel, 17/09/2026).

IDEMPOTENT — safe to re-run on sandbox AND production:
  * a person is matched by official emp code first (names must match), else by phone
    (catches people who self-registered under an auto-assigned code)
  * self-registered duplicates are MERGED into the official roster row (Excel emp
    code + English name + designation win; account gets approved)
  * Excel emp codes WIN: a different person squatting on an official code is
    re-numbered to the next free code (owner decision, 2026-06)
  * nothing is deleted — a redundant duplicate account is deactivated and its
    phone freed so the official account can take it
  * every run that changes anything writes ONE employees.roster_import audit event

Run:  cd /app/backend && python -m scripts.import_agriculture_2026
"""
import asyncio

from sqlalchemy import select

from app.audit import write_audit
from app.database import SessionLocal
from app.models import Employee, ShiftAssignment
from app.shift_logic import now_ist

DEPT = "AGRICULTURE"

# Designation → role ladder (mirrors the conventions already in the live DB:
# field/officer cadre = Staff, clerical cadre = Clerk, support = Worker).
ROLE_BY_DESIG = {
    "Agriculture Officer": "Staff",
    "Cane Supply Officer": "Staff",
    "Agriculture Overseer": "Staff",
    "Fieldman": "Staff",
    "Sr. Clerk": "Clerk",
    "Clerk": "Clerk",
    "Slipboy": "Clerk",
    "Peon": "Worker",
}

# (emp_code, full_name, 10-digit phone, designation) — verbatim from the Excel.
ROSTER = [
    ("0091", "Ghugarkar Sudam Ramdas", "9689594644", "Agriculture Officer"),
    ("0093", "Tanpure Dipak Bhausaheb", "8975716521", "Cane Supply Officer"),
    ("0095", "Ransing Ganesh Suresh", "9130209183", "Sr. Clerk"),
    ("0096", "Gorkshnath Mohan Shinde", "7397936494", "Peon"),
    ("0098", "Shirsath Venunath Bapu", "8010878862", "Cane Supply Officer"),
    ("0101", "Kale Bharat Shankar", "8007078413", "Cane Supply Officer"),
    ("0094", "Mhase Ashok Sampat", "9370344809", "Clerk"),
    ("0103", "Tapare Vijay Hanumant", "8380077824", "Fieldman"),
    ("0102", "Tanpure Santosh Abasaheb", "9175965031", "Agriculture Overseer"),
    ("0104", "Chandre Ravindra Sitaram", "9158419345", "Fieldman"),
    ("0106", "Somnath Bapusaheb Tarde", "9527271419", "Fieldman"),
    ("0107", "Dhokane Amol Dilip", "9096226090", "Fieldman"),
    ("0108", "Kokate Suraj Vasant", "9270581254", "Fieldman"),
    ("0119", "Gosavi Ashok Goraxpuri", "9881882897", "Slipboy"),
    ("0122", "Chandre Mukesh Machindra", "7758005264", "Slipboy"),
    ("0723", "Bade Prakash Eknath", "9764708031", "Agriculture Overseer"),
    ("0112", "Gandhale Narayan Dyandev", "9975652960", "Slipboy"),
    ("0113", "Bachakar Somnath Bolhaji", "7498967317", "Slipboy"),
    ("0114", "Kadam Sharad Vitthal", "7498686982", "Slipboy"),
    ("0116", "Shekh Harun Badashaha", "7020991579", "Slipboy"),
    ("0117", "Kalhapure Vijaykumar Shankar", "9970425583", "Slipboy"),
    ("0120", "Khilari Pradeep Lingdev", "9307831638", "Slipboy"),
    ("0129", "Vitnor Karnasaheb Dadasaheb", "8329083654", "Slipboy"),
    ("0133", "Shelake Sitaram Bajirav", "9665727531", "Slipboy"),
    ("0134", "Anap Narendra Maruti", "9850203723", "Slipboy"),
    ("0143", "Kalamkar Ramesh Bhausaheb", "9657601624", "Slipboy"),
    ("0741", "Gaikwad Sandip Changdev", "9503636032", "Fieldman"),
    ("0789", "Mule Umesh Ashokrao", "9822500625", "Fieldman"),
    ("0951", "Todmal Vikas Suresh", "9922594715", "Slipboy"),
    ("0126", "Nivare Subhash Sopanrao", "9604317373", "Agriculture Overseer"),
    ("0713", "Sawant Yogesh Nivrutti", "8830921341", "Agriculture Overseer"),
    ("0105", "Kohakde Sharad Indrabhan", "9657021209", "Fieldman"),
    ("0140", "Tarde Haribhau Dinkar", "9096921440", "Slipboy"),
    ("0142", "Nimbalkar Yogesh Subhash", "9322186906", "Slipboy"),
    ("0990", "Gawali Prashant Ramesh", "7020244707", "Slipboy"),
    ("0519", "Batule Babu Maruti", "9657436868", "Agriculture Overseer"),
    ("1221", "Harade Chandrbhan Narayan", "9579828028", "Fieldman"),
    ("1223", "Pawar Utkarsh Gavradhan", "9309811081", "Slipboy"),
    ("0543", "Hari Keshav Damale", "9822636022", "Slipboy"),
    ("0127", "Telore Subhash Sayaji", "9730452489", "Slipboy"),
    ("0130", "Kale Vijay Sopan", "8847734424", "Slipboy"),
    ("0097", "Thorat Sopan Eknath", "9623099031", "Agriculture Overseer"),
    ("0092", "Musmade Rajendra Sahebrao", "9665694409", "Agriculture Overseer"),
    ("1230", "Dhumak Karan Bhagwan", "9284491060", "Slipboy"),
    ("0110", "Deshmukh Mukund Mahadev", "9881307845", "Slipboy"),
    ("0131", "Sangale Dattatray Vitthal", "9881630673", "Slipboy"),
]


def _tokens(name: str) -> set[str]:
    return {t for t in name.lower().replace(".", " ").split() if t}


def _same_person(a: str, b: str) -> bool:
    """Lenient (order-insensitive) match — Marathi-script names never match an
    English roster name, which is exactly what routes them to the phone check."""
    return len(_tokens(a) & _tokens(b)) >= 2


async def run() -> None:
    async with SessionLocal() as s:
        emps = (
            await s.execute(select(Employee).where(Employee.is_demo.is_(False)))
        ).scalars().all()
        by_code = {e.emp_id: e for e in emps}
        by_phone = {e.phone: e for e in emps if e.phone}
        # allocate re-numbered codes in the normal 4-digit series — a few legacy
        # rows carry junk 6-7 digit codes and must not drag the sequence up
        numeric = [int(e.emp_id) for e in emps if e.emp_id.isdigit() and int(e.emp_id) <= 9999]
        next_free = (max(numeric) + 1) if numeric else 1

        def alloc_code() -> str:
            nonlocal next_free
            while str(next_free).zfill(4) in by_code:
                next_free += 1
            code = str(next_free).zfill(4)
            next_free += 1
            return code

        report: dict[str, list[str]] = {
            "created": [], "merged": [], "updated": [],
            "renumbered": [], "deactivated_dupes": [], "unchanged": [],
        }

        async def renumber(holder: Employee) -> None:
            old = holder.emp_id
            new_code = alloc_code()
            by_code.pop(old, None)
            holder.emp_id = new_code
            by_code[new_code] = holder
            report["renumbered"].append(f"{old} ({holder.full_name}) -> {new_code}")
            await s.flush()

        for code, name, ph10, desig in ROSTER:
            phone = f"+91{ph10}"
            holder = by_code.get(code)
            target = by_phone.get(phone)
            person: Employee | None = None

            if holder is not None and _same_person(holder.full_name, name):
                person = holder
                if target is not None and target.id != holder.id:
                    # same person has a second self-registered account — retire it
                    by_phone.pop(target.phone, None)
                    target.phone = None
                    target.is_active = False
                    target.designation = f"Duplicate — merged into {code}"
                    report["deactivated_dupes"].append(f"{target.emp_id} ({target.full_name}) -> {code}")
                    await s.flush()
            elif target is not None:
                person = target  # self-registered under an auto code — merge in place
                if holder is not None and holder.id != target.id:
                    await renumber(holder)  # different person on the official code
            elif holder is not None:
                await renumber(holder)  # official code held by a different person

            if person is None:
                person = Employee(
                    emp_id=code, full_name=name, phone=phone, department_code=DEPT,
                    designation=desig, role_code=ROLE_BY_DESIG[desig], language_pref="mr",
                    shift_swap_eligible=True, onboarding_status="approved", is_active=True,
                )
                s.add(person)
                await s.flush()
                by_code[code] = person
                by_phone[phone] = person
                report["created"].append(f"{code} {name} ({desig})")
            else:
                changes: list[str] = []
                selfreg = (
                    person.designation == "Self Registered Worker"
                    or person.onboarding_status != "approved"
                )
                if person.emp_id != code:
                    changes.append(f"emp_id {person.emp_id}->{code}")
                    by_code.pop(person.emp_id, None)
                    person.emp_id = code
                    by_code[code] = person
                if person.phone != phone:
                    other = by_phone.get(phone)
                    if other is not None and other.id != person.id:
                        print(f"!! phone {phone} still held by {other.emp_id} — NOT updating {code}")
                    else:
                        changes.append(f"phone {person.phone}->{phone}")
                        by_phone.pop(person.phone, None)
                        person.phone = phone
                        by_phone[phone] = person
                if selfreg:
                    if person.full_name != name:
                        changes.append(f"name {person.full_name!r}->{name!r}")
                        person.full_name = name
                    if person.role_code != ROLE_BY_DESIG[desig]:
                        changes.append(f"role {person.role_code}->{ROLE_BY_DESIG[desig]}")
                        person.role_code = ROLE_BY_DESIG[desig]
                if person.department_code != DEPT:
                    changes.append(f"dept {person.department_code}->{DEPT}")
                    person.department_code = DEPT
                if (person.designation or "") != desig:
                    changes.append(f"desig {person.designation!r}->{desig!r}")
                    person.designation = desig
                if person.onboarding_status != "approved":
                    changes.append(f"status {person.onboarding_status}->approved")
                    person.onboarding_status = "approved"
                if not person.is_active:
                    changes.append("re-activated")
                    person.is_active = True
                await s.flush()
                if changes:
                    (report["merged"] if selfreg else report["updated"]).append(
                        f"{code}: " + ", ".join(changes)
                    )
                else:
                    report["unchanged"].append(code)

            # baseline shift so punch-in works on day one
            has_shift = (
                await s.execute(
                    select(ShiftAssignment.id)
                    .where(ShiftAssignment.employee_id == person.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if has_shift is None:
                s.add(ShiftAssignment(
                    employee_id=person.id, shift_code="GEN",
                    effective_date=now_ist().date(), source="baseline",
                ))

        if any(report[k] for k in ("created", "merged", "updated", "renumbered", "deactivated_dupes")):
            await write_audit(
                s, None, "employees.roster_import", "settings", None,
                {"source": "shetki vibhag 2026-27 NEW.xlsx",
                 **{k: v for k, v in report.items() if k != "unchanged"}},
                is_demo=False,
            )
        await s.commit()

        for k, v in report.items():
            print(f"{k} ({len(v)}):")
            for line in v:
                print("   ", line)


if __name__ == "__main__":
    asyncio.run(run())
