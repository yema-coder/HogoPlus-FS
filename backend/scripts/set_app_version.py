#!/usr/bin/env python
"""Set the app_versions row that drives the mobile 'update available' gate.

Run this on the server AFTER every Play release so the in-app update banner matches the
build you just shipped. Idempotent: updates the single row (or creates it).

Usage:
    python scripts/set_app_version.py 1.0.27
    python scripts/set_app_version.py 1.0.27 --force --notes "Critical fix"
    python scripts/set_app_version.py 1.0.27 --apk-url https://.../app.apk

Equivalent HTTP call (admin/MD token required):
    curl -X PUT "$BASE/api/admin/app-version" \
      -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" \
      -d '{"latest_version":"1.0.27","force_update":false}'
"""
import argparse
import asyncio
import re
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AppVersion


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="e.g. 1.0.27")
    ap.add_argument("--apk-url", default=None)
    ap.add_argument("--notes", default=None)
    ap.add_argument("--force", action="store_true", help="blocking (IMMEDIATE) update")
    args = ap.parse_args()

    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", args.version):
        print(f"ERROR: version '{args.version}' must look like 1.0.27", file=sys.stderr)
        return 2

    async with SessionLocal() as session:
        row = (
            await session.execute(select(AppVersion).order_by(AppVersion.updated_at.desc()).limit(1))
        ).scalar_one_or_none()
        if row is None:
            row = AppVersion(latest_version=args.version)
            session.add(row)
        prev = row.latest_version if row.id else None
        row.latest_version = args.version
        if args.apk_url is not None:
            row.apk_url = args.apk_url
        if args.notes is not None:
            row.notes = args.notes
        row.force_update = bool(args.force)
        await session.commit()
        print(f"app_versions.latest_version: {prev!r} -> {args.version!r} (force={row.force_update})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
