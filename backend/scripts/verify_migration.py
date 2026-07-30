"""Migration integrity verifier: compares SOURCE (Neon) vs TARGET (RDS).

Usage:
  SOURCE_URL="postgresql://...neon..." TARGET_URL="postgresql://...rds..." \
      python scripts/verify_migration.py

Checks (all must pass):
  1. identical table sets
  2. identical row counts per table
  3. md5 checksums over ordered business-critical columns
     (employees, attendance, incidents, shift_assignments, ble_beacons, vehicle_logs)
  4. alembic_version identical
  5. pgvector present on target + embedding row parity
  6. sequences / identity next-values >= source
"""
import asyncio
import os
import sys

import asyncpg

CHECKSUM_TABLES = {
    "employees": "emp_id, phone, full_name, department_code, role_code, onboarding_status, is_active",
    "attendance": "employee_id::text, date::text, verification_level::text",
    "incidents": "id::text, status::text, severity::text, department_code",
    "shift_assignments": "id::text, employee_id::text, date::text",
    "ble_beacons": "id::text, uuid, major::text, minor::text, is_active::text",
    "vehicle_logs": "id::text, plate, direction, logged_at::text",
}

failures: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'} | {name} {extra}")
    if not cond:
        failures.append(name)


async def connect(url: str):
    return await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://").replace("?ssl=require", ""), ssl="require" if "neon" in url or "rds" in url or "amazonaws" in url else None)


async def main() -> None:
    src = await connect(os.environ["SOURCE_URL"])
    dst = await connect(os.environ["TARGET_URL"])

    q_tables = "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    s_tables = [r["tablename"] for r in await src.fetch(q_tables)]
    d_tables = [r["tablename"] for r in await dst.fetch(q_tables)]
    check("table sets identical", s_tables == d_tables, f"src={len(s_tables)} dst={len(d_tables)}")

    for t in s_tables:
        sc = await src.fetchval(f'SELECT COUNT(*) FROM "{t}"')
        dc = await dst.fetchval(f'SELECT COUNT(*) FROM "{t}"') if t in d_tables else -1
        check(f"rowcount {t}", sc == dc, f"{sc} vs {dc}")

    for t, cols in CHECKSUM_TABLES.items():
        if t not in s_tables:
            continue
        q = f"SELECT md5(string_agg(concat_ws('|', {cols}), ';' ORDER BY 1)) FROM \"{t}\""
        check(f"checksum {t}", await src.fetchval(q) == await dst.fetchval(q))

    sv = await src.fetchval("SELECT version_num FROM alembic_version")
    dv = await dst.fetchval("SELECT version_num FROM alembic_version")
    check("alembic head identical", sv == dv, f"{sv} vs {dv}")

    has_vec = await dst.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname='vector'")
    check("pgvector installed on target", has_vec == 1)
    emb_tables = [
        r["table_name"] for r in await src.fetch(
            "SELECT DISTINCT table_name FROM information_schema.columns WHERE udt_name='vector'"
        )
    ]
    for t in emb_tables:
        se = await src.fetchval(f'SELECT COUNT(*) FROM "{t}"')
        de = await dst.fetchval(f'SELECT COUNT(*) FROM "{t}"')
        check(f"embedding rows {t}", se == de, f"{se} vs {de}")

    seqs = [r["sequencename"] for r in await src.fetch("SELECT sequencename FROM pg_sequences WHERE schemaname='public'")]
    for s in seqs:
        sl = await src.fetchval(f"SELECT last_value FROM \"{s}\"")
        dl = await dst.fetchval(f"SELECT last_value FROM \"{s}\"")
        check(f"sequence {s}", dl >= sl, f"{sl} vs {dl}")

    await src.close()
    await dst.close()
    print("\n" + ("ALL CHECKS PASS" if not failures else f"{len(failures)} FAILURES: {failures}"))
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    asyncio.run(main())
