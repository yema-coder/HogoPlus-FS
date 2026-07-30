"""Evidence: run the ACTUAL backend resolver (app.ble.resolve_beacon) against the
production DB for every new minor, plus negative controls."""
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from app.ble import beacon_ref, resolve_beacon  # noqa: E402
from app.database import SessionLocal  # noqa: E402

UUID = "01122334-4556-6778-899A-ABBCCDDEEFF0"  # deliberately UPPERCASE (matcher is case-insensitive)
NEW_MINORS = [29, 27, 12, 2, 3, 22, 14, 17, 5, 25, 16, 35, 0, 1, 30, 9, 11, 31, 19, 28, 23, 20, 21]


async def main() -> None:
    async with SessionLocal() as session:
        print("RESOLVER OUTPUT (app.ble.resolve_beacon, production DB):")
        for m in NEW_MINORS:
            b = await resolve_beacon(session, ibeacon_uuid=UUID, major=1, minor=m)
            ref = beacon_ref(ibeacon_uuid=UUID, major=1, minor=m)
            zone = f"{b.zone_label_en} / {b.zone_label_hi} / {b.zone_label_mr}" if b else "NO MATCH"
            print(f"  minor={m:<3} -> {zone}   stored_ref={ref}")

        print("\nNEGATIVE CONTROLS:")
        for m in (999, 6):  # 999 never installed; 6 not in the plan either
            b = await resolve_beacon(session, ibeacon_uuid=UUID, major=1, minor=m)
            print(f"  minor={m:<3} -> {'MATCH (BUG!)' if b else 'None (correctly unmatched)'}")
        b = await resolve_beacon(session, ibeacon_uuid=UUID, major=2, minor=0)  # wrong major
        print(f"  major=2 minor=0 -> {'MATCH (BUG!)' if b else 'None (correctly unmatched)'}")


asyncio.run(main())
