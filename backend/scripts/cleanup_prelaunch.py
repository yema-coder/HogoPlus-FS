#!/usr/bin/env python3
"""PRE-LAUNCH DATA CLEANUP — remove REAL-SIDE (is_demo=false) TEST data so every
department starts Monday with clean dashboards, while preserving ALL real config,
employees, the demo bubble, and the audit log.

RUN ON THE MUMBAI HOST (both Neon + R2 creds present):
    docker compose exec backend python scripts/cleanup_prelaunch.py            # DRY RUN (default)
    docker compose exec backend python scripts/cleanup_prelaunch.py --execute  # after you approve

SAFETY (matches the campaign requirements):
  * Row-level DELETEs only — NO drop/truncate/schema changes, ever.
  * --execute confirms a FRESH R2 backup exists first; aborts if none < BACKUP_MAX_AGE_H.
  * Everything runs inside ONE transaction (rolls back cleanly on any error).
  * Children deleted before parents (FK-safe); zero-orphan check afterwards.
  * Prints per-table BEFORE/AFTER counts + explicit preservation confirmation.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402

BACKUP_MAX_AGE_H = 6  # a backup must be newer than this before --execute proceeds

# ----- what gets DELETED (real side only, is_demo=false) -----------------------
# Ordered children-before-parents. incident_timeline has NO is_demo column, so it
# is scoped via its parent incidents. notifications covers test announcements too.
DELETE_STEPS = [
    ("incident_timeline (real-incident history/comments)",
     "DELETE FROM incident_timeline WHERE incident_id IN (SELECT id FROM incidents WHERE is_demo = false)"),
    ("incidents (+AI/escalation/resolution/media refs on-row)",
     "DELETE FROM incidents WHERE is_demo = false"),
    ("attendance (all punches incl. flagged)",
     "DELETE FROM attendance WHERE is_demo = false"),
    ("form_submissions (all 13 depts)",
     "DELETE FROM form_submissions WHERE is_demo = false"),
    ("shift_swap_requests (+responses/approvals on-row)",
     "DELETE FROM shift_swap_requests WHERE is_demo = false"),
    ("notifications (alerts + test announcements)",
     "DELETE FROM notifications WHERE is_demo = false"),
    ("chat_messages (Sahayak test chats — worker-visible)",
     "DELETE FROM chat_messages WHERE is_demo = false"),
]

# Count queries mirroring each DELETE (same WHERE) for the dry-run table.
COUNT_FOR_DELETE = [(label, sql.replace("DELETE FROM", "SELECT count(*) FROM", 1)) for label, sql in DELETE_STEPS]

# ----- the self-registered test account "Eyam" --------------------------------
EYAM_WHERE = "emp_id = '1217' AND is_demo = false AND onboarding_status = 'pending_approval' AND department_code IS NULL"

# ----- tables we PROVE are untouched (preserved) ------------------------------
PRESERVE_TABLES = [
    "employees", "departments", "form_definitions", "ble_beacons", "settings",
    "shifts", "roles", "shift_assignments", "sop_docs", "sop_chunks", "audit_events",
]
# reported-but-NOT-deleted (not in the delete list) so you can decide separately:
REPORT_ONLY = [
    ("otp_attempts (OTP send log — KEPT for launch-day debugging)", "SELECT count(*) FROM otp_attempts"),
]


async def _scalar(session, sql: str) -> int:
    return int((await session.execute(text(sql))).scalar() or 0)


async def check_backup() -> tuple[bool, str]:
    """Confirm a fresh R2 backup exists. Returns (ok, message with key+timestamp)."""
    try:
        from app.storage import S3Storage, get_storage

        storage = get_storage()
        if not isinstance(storage, S3Storage):
            return False, ("FILE_STORAGE_MODE is not S3/R2 in this environment — cannot verify a "
                           "backup. Run this on the Mumbai host where R2 is configured.")
        resp = storage.client.list_objects_v2(Bucket=storage.bucket, Prefix="backups/")
        objs = sorted(resp.get("Contents", []), key=lambda o: o["LastModified"], reverse=True)
        if not objs:
            return False, "NO backup objects found under backups/ in R2 — STOP."
        newest = objs[0]
        age = datetime.now(timezone.utc) - newest["LastModified"].astimezone(timezone.utc)
        ok = age <= timedelta(hours=BACKUP_MAX_AGE_H)
        return ok, (f"latest backup key={newest['Key']} "
                    f"timestamp={newest['LastModified'].astimezone(timezone.utc).isoformat()} "
                    f"age={age.total_seconds()/3600:.1f}h "
                    f"({'FRESH' if ok else f'STALE > {BACKUP_MAX_AGE_H}h — STOP'})")
    except Exception as e:  # noqa: BLE001
        return False, f"backup check failed: {type(e).__name__}: {e}"


async def snapshot(session) -> dict[str, int]:
    tables = [
        "incidents", "incident_timeline", "attendance", "form_submissions",
        "shift_swap_requests", "notifications", "chat_messages", "otp_attempts",
        "employees", "departments", "form_definitions", "ble_beacons", "settings",
        "shifts", "roles", "shift_assignments", "sop_docs", "sop_chunks", "audit_events",
    ]
    out = {}
    for t in tables:
        out[t] = await _scalar(session, f"SELECT count(*) FROM {t}")
    return out


async def preserve_counts(session) -> dict[str, tuple[int, int]]:
    """(total, real-side) for each preserved table."""
    out = {}
    for t in PRESERVE_TABLES:
        total = await _scalar(session, f"SELECT count(*) FROM {t}")
        if t in ("employees", "audit_events", "shift_assignments", "form_submissions"):
            has_demo = await _scalar(
                session,
                f"SELECT count(*) FROM information_schema.columns WHERE table_name='{t}' AND column_name='is_demo'",
            )
            real = await _scalar(session, f"SELECT count(*) FROM {t} WHERE is_demo = false") if has_demo else total
        else:
            real = total
        out[t] = (total, real)
    return out


async def run(execute: bool) -> None:
    async with SessionLocal() as session:
        print("=" * 78)
        print(f"PRE-LAUNCH CLEANUP  —  mode={'EXECUTE' if execute else 'DRY RUN'}")
        print(f"DATABASE host: {settings.database_url.split('@')[-1].split('/')[0]}")
        print("=" * 78)

        # ---- backup gate (execute only) --------------------------------------
        ok, msg = await check_backup()
        print(f"\n[R2 BACKUP] {msg}")
        if execute and not ok:
            print("\n*** ABORTING — no fresh R2 backup. Run the backup job, then retry. ***")
            return

        # ---- would-delete numbers -------------------------------------------
        print("\n---- ROWS THAT WOULD BE DELETED (real side, is_demo=false) ----")
        total_del = 0
        for label, sql in COUNT_FOR_DELETE:
            n = await _scalar(session, sql)
            total_del += n
            print(f"  {n:>7}  {label}")
        eyam = await _scalar(session, f"SELECT count(*) FROM employees WHERE {EYAM_WHERE}")
        eyam_sa = await _scalar(session, f"SELECT count(*) FROM shift_assignments WHERE employee_id IN (SELECT id FROM employees WHERE {EYAM_WHERE})")
        eyam_audit = await _scalar(session, f"SELECT count(*) FROM audit_events WHERE actor_id IN (SELECT id FROM employees WHERE {EYAM_WHERE})")
        print(f"  {eyam:>7}  employees — test account 'Eyam' (+{eyam_sa} shift_assignment, {eyam_audit} audit actor_id → NULLed, kept)")
        print(f"  ------- \n  {total_del + eyam:>7}  TOTAL rows deleted (+{eyam_sa} Eyam child rows)")

        # ---- reported but NOT deleted ---------------------------------------
        print("\n---- REPORTED, NOT DELETED (decide separately) ----")
        for label, sql in REPORT_ONLY:
            print(f"  {await _scalar(session, sql):>7}  {label}")

        # ---- preserved ------------------------------------------------------
        print("\n---- PRESERVED (total / real-side) ----")
        pres = await preserve_counts(session)
        for t, (tot, real) in pres.items():
            print(f"  {tot:>7} / {real:<7}  {t}")
        demo_bubble = await _scalar(session, "SELECT count(*) FROM employees WHERE is_demo = true")
        print(f"  demo bubble (employees is_demo=true) untouched: {demo_bubble}")

        if not execute:
            print("\nDRY RUN complete — no rows changed. Re-run with --execute after approval.")
            return

        # ---- EXECUTE: single transaction ------------------------------------
        print("\n---- EXECUTING (single transaction) ----")
        before = await snapshot(session)
        try:
            async with session.begin():
                for label, sql in DELETE_STEPS:
                    res = await session.execute(text(sql))
                    print(f"  deleted {res.rowcount:>7}  {label}")
                # Eyam: null the audit actor (preserve history), drop child assignment, drop account
                await session.execute(text(
                    f"UPDATE audit_events SET actor_id = NULL WHERE actor_id IN (SELECT id FROM employees WHERE {EYAM_WHERE})"))
                await session.execute(text(
                    f"DELETE FROM shift_assignments WHERE employee_id IN (SELECT id FROM employees WHERE {EYAM_WHERE})"))
                r = await session.execute(text(f"DELETE FROM employees WHERE {EYAM_WHERE}"))
                print(f"  deleted {r.rowcount:>7}  employees — 'Eyam'")
        except Exception as e:  # noqa: BLE001
            print(f"\n*** TRANSACTION ROLLED BACK — {type(e).__name__}: {e} — NO CHANGES MADE ***")
            raise

        after = await snapshot(session)

        # ---- orphan re-check ------------------------------------------------
        orphans = {
            "incident_timeline→incidents": "SELECT count(*) FROM incident_timeline t LEFT JOIN incidents i ON i.id=t.incident_id WHERE i.id IS NULL",
            "attendance→employees": "SELECT count(*) FROM attendance a LEFT JOIN employees e ON e.id=a.employee_id WHERE e.id IS NULL",
            "form_submissions→employees": "SELECT count(*) FROM form_submissions f LEFT JOIN employees e ON e.id=f.submitted_by WHERE e.id IS NULL",
            "shift_assignments→employees": "SELECT count(*) FROM shift_assignments s LEFT JOIN employees e ON e.id=s.employee_id WHERE e.id IS NULL",
            "notifications→employees": "SELECT count(*) FROM notifications n LEFT JOIN employees e ON e.id=n.recipient_id WHERE e.id IS NULL",
        }
        print("\n---- BEFORE / AFTER + orphan check ----")
        for t in before:
            print(f"  {t:<22} {before[t]:>7} -> {after[t]:<7}")
        all_clean = True
        for label, sql in orphans.items():
            n = await _scalar(session, sql)
            all_clean = all_clean and n == 0
            print(f"  ORPHANS {label}: {n}")

        # ---- preservation assertions ----------------------------------------
        print("\n---- PRESERVATION CONFIRMATION ----")
        checks = {
            "employees (real preserved)": after["employees"] == before["employees"] - eyam,
            "departments intact": after["departments"] == before["departments"],
            "form_definitions intact": after["form_definitions"] == before["form_definitions"],
            "ble_beacons intact": after["ble_beacons"] == before["ble_beacons"],
            "settings intact": after["settings"] == before["settings"],
            "sop_docs intact": after["sop_docs"] == before["sop_docs"],
            "audit_events kept": after["audit_events"] == before["audit_events"],
            "demo bubble untouched": await _scalar(session, "SELECT count(*) FROM employees WHERE is_demo=true") == demo_bubble,
            "real incidents = 0": after["incidents"] == await _scalar(session, "SELECT count(*) FROM incidents WHERE is_demo=true"),
            "no orphans": all_clean,
        }
        for k, v in checks.items():
            print(f"  [{'OK' if v else 'FAIL'}] {k}")
        print("\nCLEANUP COMPLETE." if all(checks.values()) else "\n*** POST-CHECK FAILURES — REVIEW ABOVE ***")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="perform deletions (default is dry run)")
    args = ap.parse_args()
    asyncio.run(run(execute=args.execute))


if __name__ == "__main__":
    main()
