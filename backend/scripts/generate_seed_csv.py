"""Generates seed_employees.csv (401 rows) — synthetic but realistic mill records.
Deterministic (seeded RNG). Replace with the real CSV anytime; seed.py is idempotent.

Columns: emp_id,full_name,phone,department_code,designation,role_code,shift_swap_eligible,phone_status,language_pref
"""
import csv
import random
from pathlib import Path

random.seed(42)

OUT = Path(__file__).resolve().parent.parent / "seed_employees.csv"

FIRST = [
    "Ramesh", "Suresh", "Ganesh", "Mahesh", "Prakash", "Vitthal", "Dattatray", "Sachin",
    "Sanjay", "Vijay", "Ajay", "Anil", "Sunil", "Rajesh", "Santosh", "Kailas", "Bhausaheb",
    "Balasaheb", "Tukaram", "Namdev", "Pandurang", "Shivaji", "Sambhaji", "Nitin", "Sagar",
    "Swapnil", "Amol", "Rahul", "Rohit", "Vikas", "Dinesh", "Kiran", "Manoj", "Popat",
    "Eknath", "Dnyaneshwar", "Hanumant", "Jalindar", "Laxman", "Madhukar", "Onkar",
    "Pravin", "Raosaheb", "Shantaram", "Trimbak", "Uttam", "Vasant", "Yashwant",
    "Sunita", "Vandana", "Manisha", "Archana", "Savita", "Rekha", "Shobha", "Mangal",
    "Jyoti", "Kavita", "Ashwini", "Pooja",
]
LAST = [
    "Patil", "Deshmukh", "Jadhav", "Shinde", "Pawar", "More", "Gaikwad", "Kale", "Chavan",
    "Bhosale", "Kadam", "Salunkhe", "Thorat", "Mane", "Kamble", "Waghmare", "Sawant",
    "Dhumal", "Nikam", "Ghadge", "Lokhande", "Shelar", "Suryawanshi", "Yadav", "Zende",
    "Ingale", "Bansode", "Gholap", "Autade", "Rendal",
]

STAFF_DESIGNATIONS = {
    "PRODUCTION": ["Chemist", "Lab Assistant", "Shift Supervisor", "Pan In-Charge"],
    "ENGINEERING": ["Junior Engineer", "Electrical Engineer", "Instrumentation Technician"],
    "DISTILLERY": ["Distillery Chemist", "Shift Supervisor"],
    "AGRICULTURE": ["Agriculture Officer", "Cane Development Officer"],
    "ACCOUNTS": ["Accountant", "Assistant Accountant"],
    "ADMIN": ["Welfare Officer", "Computer Operator"],
    "STORE": ["Store Keeper", "Assistant Store Keeper"],
    "CANE_YARD": ["Weighbridge Operator", "Yard Supervisor"],
    "SECURITY": ["Security Havaldar"],
    "TIME_OFFICE": ["Time Keeper"],
    "PURCHASE": ["Purchase Assistant"],
    "GODOWN": ["Godown Keeper"],
    "CIVIL": ["Civil Overseer"],
}
CLERK_DESIGNATIONS = ["Clerk", "Junior Clerk", "Cane Clerk", "Bill Clerk", "Godown Clerk", "Record Clerk"]
WORKER_DESIGNATIONS = {
    "PRODUCTION": ["Pan Operator", "Centrifugal Operator", "Boiler Attendant", "Machine Operator", "Helper", "Mazdoor"],
    "ENGINEERING": ["Fitter", "Turner", "Welder", "Electrician", "Wireman", "Helper", "Khalashi"],
    "DISTILLERY": ["Still Operator", "Fermentation Attendant", "Helper", "Mazdoor"],
    "CANE_YARD": ["Crane Operator", "Unloader", "Hamal", "Mazdoor"],
    "SECURITY": ["Security Guard", "Watchman", "Gate Keeper"],
    "AGRICULTURE": ["Field Mazdoor", "Nursery Worker", "Driver"],
    "STORE": ["Hamal", "Helper"],
    "GODOWN": ["Hamal", "Bag Stacker", "Helper"],
    "CIVIL": ["Mason", "Carpenter", "Plumber", "Helper"],
    "ADMIN": ["Peon", "Sweeper", "Gardener", "Driver"],
    "ACCOUNTS": ["Peon"],
    "PURCHASE": ["Peon"],
    "TIME_OFFICE": ["Peon"],
}

# dept -> worker count (total workers = 324)
WORKER_DIST = {
    "PRODUCTION": 68, "ENGINEERING": 58, "CANE_YARD": 40, "DISTILLERY": 34,
    "SECURITY": 30, "AGRICULTURE": 26, "GODOWN": 18, "STORE": 14, "CIVIL": 14,
    "ADMIN": 10, "ACCOUNTS": 5, "PURCHASE": 4, "TIME_OFFICE": 3,
}
# dept -> staff count (total staff = 40)
STAFF_DIST = {
    "PRODUCTION": 7, "ENGINEERING": 6, "DISTILLERY": 4, "AGRICULTURE": 4,
    "ACCOUNTS": 4, "ADMIN": 3, "STORE": 3, "CANE_YARD": 3, "SECURITY": 2,
    "TIME_OFFICE": 1, "PURCHASE": 1, "GODOWN": 1, "CIVIL": 1,
}
# dept -> clerk count (total clerks = 30)
CLERK_DIST = {
    "ACCOUNTS": 5, "TIME_OFFICE": 4, "STORE": 4, "PURCHASE": 3, "GODOWN": 3,
    "ADMIN": 3, "CANE_YARD": 3, "AGRICULTURE": 2, "PRODUCTION": 1,
    "ENGINEERING": 1, "DISTILLERY": 1, "CIVIL": 0, "SECURITY": 0,
}

MANAGERS = [
    ("PRODUCTION", "Production Manager"),
    ("ENGINEERING", "Chief Engineer"),
    ("SECURITY", "Chief Security Officer"),
    ("TIME_OFFICE", "Time Office In-Charge"),
    ("ACCOUNTS", "Chief Accountant"),
    ("STORE", "Stores Manager"),
]

BAD_PHONE_ROWS = {101, 150, 200, 250, 300, 350}  # row index (1-based emp number)


def name():
    return f"{random.choice(FIRST)} {random.choice(LAST)}"


def main():
    rows = []
    counter = 0

    def next_emp():
        nonlocal counter
        counter += 1
        return f"{counter:04d}"

    phone_seq = 0

    def next_phone():
        nonlocal phone_seq
        phone_seq += 1
        return f"+919{700000000 + phone_seq}"

    def eligible(role, dept):
        return "true" if (role == "Worker" or (dept == "SECURITY" and role != "Manager")) else "false"

    # 1) CGM
    rows.append([next_emp(), "Rajendra Deshmukh", next_phone(), "ADMIN",
                 "Chief General Manager", "CGM", "false", "OK", "en"])
    # 2) 6 Managers (7 departments intentionally left without a Manager)
    for dept, desig in MANAGERS:
        rows.append([next_emp(), name(), next_phone(), dept, desig, "Manager", "false", "OK", "en"])
    # 3) Staff
    for dept, count in STAFF_DIST.items():
        for _ in range(count):
            desig = random.choice(STAFF_DESIGNATIONS.get(dept, ["Staff Assistant"]))
            rows.append([next_emp(), name(), next_phone(), dept, desig, "Staff",
                         eligible("Staff", dept), "OK", random.choice(["mr", "mr", "hi"])])
    # 4) Clerks
    for dept, count in CLERK_DIST.items():
        for _ in range(count):
            rows.append([next_emp(), name(), next_phone(), dept, random.choice(CLERK_DESIGNATIONS),
                         "Clerk", eligible("Clerk", dept), "OK", random.choice(["mr", "mr", "hi"])])
    # 5) Workers
    for dept, count in WORKER_DIST.items():
        for _ in range(count):
            emp = next_emp()
            n = int(emp)
            status = "OK"
            phone = next_phone()
            if n in BAD_PHONE_ROWS:
                status = random.choice(["MISSING", "INVALID"])
                phone = ""
            rows.append([emp, name(), phone, dept, random.choice(WORKER_DESIGNATIONS[dept]),
                         "Worker", "true", status, "mr"])

    assert len(rows) == 401, f"expected 401 rows, got {len(rows)}"
    bad = sum(1 for r in rows if r[7] != "OK")
    assert bad == 6, f"expected 6 bad-phone rows, got {bad}"

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["emp_id", "full_name", "phone", "department_code", "designation",
                    "role_code", "shift_swap_eligible", "phone_status", "language_pref"])
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT} ({bad} rows with phone_status != OK)")


if __name__ == "__main__":
    main()
