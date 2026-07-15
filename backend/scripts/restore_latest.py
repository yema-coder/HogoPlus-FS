"""DISASTER RECOVERY — restore a PostgreSQL backup from R2.

Usage:
    cd /app/backend
    python scripts/restore_latest.py                # list available backups
    python scripts/restore_latest.py --key backups/2026-07-14/0030.sql.gz --yes
    python scripts/restore_latest.py --latest --yes # restore the newest backup
    python scripts/restore_latest.py --latest --yes --target hogoplus_drill  # scratch DB drill

Restores into the target database (default: the one in DATABASE_URL), then re-runs
`alembic upgrade head`. Requires --yes to actually touch the database.
"""
import argparse
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.storage import S3Storage  # noqa: E402


def list_backups(s3: S3Storage) -> list[str]:
    resp = s3.client.list_objects_v2(Bucket=s3.bucket, Prefix="backups/")
    return sorted((o["Key"] for o in resp.get("Contents", [])), reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="exact backup key to restore")
    ap.add_argument("--latest", action="store_true", help="restore the newest backup")
    ap.add_argument("--yes", action="store_true", help="required to actually restore")
    ap.add_argument("--target", help="target database name (default: from DATABASE_URL)")
    args = ap.parse_args()

    s3 = S3Storage()
    keys = list_backups(s3)
    if not keys:
        print("No backups found in R2")
        sys.exit(1)

    if not args.key and not args.latest:
        print("Available backups (newest first):")
        for k in keys:
            print(" ", k)
        print("\nRe-run with --key <key> --yes  (or --latest --yes)")
        return

    key = args.key or keys[0]
    if key not in keys:
        print(f"Backup not found: {key}")
        sys.exit(1)
    if not args.yes:
        print(f"Would restore {key}. Re-run with --yes to proceed. THIS OVERWRITES DATA.")
        sys.exit(1)

    parsed = urlparse(settings.database_url.replace("+asyncpg", ""))
    dbname = args.target or (parsed.path or "/postgres").lstrip("/")
    host, port = parsed.hostname or "127.0.0.1", str(parsed.port or 5432)
    user, pw = parsed.username or "postgres", parsed.password or ""
    env = {"PGPASSWORD": pw}

    print(f"Downloading {key} …")
    raw = gzip.decompress(s3.get(key))

    print(f"Recreating database {dbname} …")
    for sql in (
        f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)',
        f'CREATE DATABASE "{dbname}"',
    ):
        subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", "postgres", "-c", sql],
            env=env, check=True, capture_output=True,
        )
    # pgvector must exist before the dump's CREATE TABLE ... vector(384) lines.
    # Works when the extension is trusted or the user is superuser; the dump's
    # own CREATE EXTENSION IF NOT EXISTS then no-ops.
    subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname, "-c",
         "CREATE EXTENSION IF NOT EXISTS vector"],
        env=env, check=True, capture_output=True,
    )

    print("Restoring dump …")
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname, "-v", "ON_ERROR_STOP=1", "-f", tmp_path],
        env=env, check=True, capture_output=True,
    )
    Path(tmp_path).unlink(missing_ok=True)

    if not args.target:  # only migrate the real DB, not scratch drills
        print("Running alembic upgrade head …")
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True,
                       cwd=str(Path(__file__).resolve().parent.parent))

    out = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname, "-t", "-c",
         "SELECT (SELECT count(*) FROM employees), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public')"],
        env=env, check=True, capture_output=True, text=True,
    ).stdout.strip()
    print(f"RESTORE COMPLETE into '{dbname}' — employees | public tables: {out}")


if __name__ == "__main__":
    main()
