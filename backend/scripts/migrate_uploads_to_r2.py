"""One-time migration: copy every file in ./uploads to R2 preserving keys.

DB rows keep the same keys (storage-agnostic). Run:
    cd /app/backend && python scripts/migrate_uploads_to_r2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.storage import S3Storage  # noqa: E402


def main() -> None:
    uploads = Path(settings.upload_dir)
    if not uploads.exists():
        print("No uploads directory — nothing to migrate")
        return
    s3 = S3Storage()
    migrated = 0
    skipped = 0
    for f in sorted(uploads.iterdir()):
        if not f.is_file():
            continue
        key = f.name
        try:
            s3.client.head_object(Bucket=s3.bucket, Key=key)
            skipped += 1
            print(f"skip (exists): {key}")
            continue
        except Exception:
            pass
        s3.client.put_object(Bucket=s3.bucket, Key=key, Body=f.read_bytes())
        migrated += 1
        print(f"migrated: {key}")
    print(f"DONE — migrated {migrated} file(s), skipped {skipped} already present")


if __name__ == "__main__":
    main()
