"""Task C(a): today's REAL-side attendance rows — beacon payload evidence. READ-ONLY."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
import asyncpg  # noqa: E402


async def main() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        """
        SELECT e.emp_id, e.full_name AS name, a.date AS att_date, a.punch_in_at,
               a.ble_beacon_id, a.ble_zone, a.verification_level, a.flagged_reason,
               (a.gps_lat IS NOT NULL) AS has_gps
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.is_demo = false
          AND a.date >= (now() AT TIME ZONE 'Asia/Kolkata')::date - 1
        ORDER BY a.punch_in_at
        """
    )
    print(f"real-side attendance rows (yesterday+today IST): {len(rows)}")
    for r in rows:
        t = r["punch_in_at"].strftime("%H:%M") if r["punch_in_at"] else "-"
        print(
            f"  {r['att_date']} {r['emp_id']:>5} {str(r['name'])[:22]:<22} in_utc={t} "
            f"beacon_ref={r['ble_beacon_id'] or 'EMPTY'} zone={r['ble_zone'] or '-'} "
            f"level={r['verification_level']} reason={r['flagged_reason'] or '-'} gps={r['has_gps']}"
        )
    b = await conn.fetch(
        "SELECT beacon_uuid, major, minor, mac_address, zone_label_en, is_active"
        " FROM ble_beacons ORDER BY minor NULLS LAST"
    )
    print(f"\nbeacon registry rows: {len(b)}")
    for x in b:
        print(
            f"  minor={x['minor']} major={x['major']} mac={x['mac_address']} "
            f"zone={x['zone_label_en']} active={x['is_active']} uuid={x['beacon_uuid']}"
        )
    await conn.close()


asyncio.run(main())
