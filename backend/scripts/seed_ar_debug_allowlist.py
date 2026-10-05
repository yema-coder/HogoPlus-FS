"""Idempotent: add Amey Ghadge (emp_id 0001, phone 8483029039) to the AR-debug
allowlist (settings.ar_debug_emp_ids) so the on-device AR debug HUD + reprojection
dot show on that REAL account — no rebuild needed. Merges; never drops existing
entries. Safe to re-run.

Usage: cd /app/backend && python scripts/seed_ar_debug_allowlist.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

WANT = ["0001", "8483029039"]  # emp_id (exact) + phone (last-10-digit match)


async def main() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.models import FactorySettings

    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sm() as session:
        s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
        if s is None:
            print("ERROR: settings row not seeded yet — run the main seed first")
            return
        existing = [t.strip() for t in (s.ar_debug_emp_ids or "").replace("\n", ",").split(",") if t.strip()]
        merged = list(existing)
        for w in WANT:
            if w not in merged:
                merged.append(w)
        s.ar_debug_emp_ids = ",".join(merged)
        await session.commit()
        print(f"ar_debug_emp_ids = {s.ar_debug_emp_ids!r}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
