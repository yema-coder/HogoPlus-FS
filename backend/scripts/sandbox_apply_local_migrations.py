"""DEV/SANDBOX ONLY — re-apply this branch's local schema deltas after a pod reset.

The sandbox recovery restores the PRODUCTION R2 backup (alembic rev 0026) and then
`alembic upgrade head` fails because the production-only 0026 migration file is not in
this workspace (we were told NOT to import main from GitHub). So after every reset the
DB is back at 0026 without this branch's 0027/0028/0029 changes.

This script applies those three migrations' DDL idempotently and stamps alembic to 0029
so the sandbox matches what the deploy will produce on production (where 0026 exists and
the 0027→0028→0029 chain applies cleanly). NOT used in production.

Run:  cd /app/backend && python scripts/sandbox_apply_local_migrations.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

DDL = [
    # 0027 — preserve the model's original plate read
    "ALTER TABLE photo_plates ADD COLUMN IF NOT EXISTS original_text varchar(20)",
    "UPDATE photo_plates SET original_text = plate_text WHERE original_text IS NULL AND edited = false",
    # 0028 — face reference collection (data only)
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS face_collection_enabled boolean NOT NULL DEFAULT false",
    """CREATE TABLE IF NOT EXISTS face_references (
        id uuid PRIMARY KEY,
        employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        attendance_id uuid REFERENCES attendance(id) ON DELETE SET NULL,
        source varchar(20) NOT NULL DEFAULT 'attendance',
        selfie_key varchar(500),
        crop_key varchar(500),
        embedding vector(128),
        embedding_dim integer,
        quality_score double precision,
        model_version varchar(40) NOT NULL,
        det_version varchar(40),
        face_x double precision, face_y double precision, face_w double precision, face_h double precision,
        image_w integer, image_h integer,
        is_demo boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_face_references_employee_id ON face_references(employee_id)",
    "CREATE INDEX IF NOT EXISTS ix_face_references_attendance_id ON face_references(attendance_id)",
    "CREATE INDEX IF NOT EXISTS ix_face_references_is_demo ON face_references(is_demo)",
    # 0029 — attendance verification ladder + location + auto punch-out
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS gps_verify_enabled boolean NOT NULL DEFAULT false",
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS gps_accuracy_max_m integer NOT NULL DEFAULT 100",
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS geofence_grace_m integer NOT NULL DEFAULT 150",
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS auto_punch_out_enabled boolean NOT NULL DEFAULT false",
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS auto_punch_out_grace_min integer NOT NULL DEFAULT 60",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS gps_accuracy double precision",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS geo_distance_m double precision",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS verification_path varchar(10)",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS geo_address varchar(300)",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS punch_out_source varchar(10)",
    # dev convenience: mark AGRICULTURE as a FIELD department (field staff work 2–78 km
    # from the mill). On production this is a one-toggle admin change, NOT hardcoded.
    "UPDATE departments SET geofence_exempt = true, beacon_exempt = true WHERE code = 'AGRICULTURE'",
    # 0030 — Mappls geocode cache + incident GPS accuracy
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS gps_accuracy double precision",
    """CREATE TABLE IF NOT EXISTS geocode_cache (
        id uuid PRIMARY KEY,
        lat_key double precision NOT NULL,
        lng_key double precision NOT NULL,
        address varchar(300),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_geocode_cache_coords UNIQUE (lat_key, lng_key)
    )""",
    "UPDATE alembic_version SET version_num = '0030'",
]


async def main() -> None:
    async with engine.begin() as c:
        for d in DDL:
            await c.execute(text(d))
    async with engine.connect() as c:
        rev = (await c.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        fr = (await c.execute(text("SELECT to_regclass('public.face_references')"))).scalar()
        print(f"OK local schema at rev={rev}; face_references={fr}")


if __name__ == "__main__":
    asyncio.run(main())
