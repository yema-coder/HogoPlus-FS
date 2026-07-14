import asyncio
import gzip
import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.celery_app import celery
from app.config import settings

logger = logging.getLogger("hogo.tasks")


async def _sweep_async() -> dict:
    from app.escalation import run_escalation_sweep

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with sm() as session:
            counts = await run_escalation_sweep(session)
            await session.commit()
        return counts
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.escalation_sweep")
def escalation_sweep() -> dict:
    counts = asyncio.run(_sweep_async())
    logger.info("Escalation sweep done: %s", counts)
    return counts


@celery.task(name="app.tasks.nightly_backup")
def nightly_backup() -> dict:
    """pg_dump -> gzip -> S3 backups/YYYY-MM-DD.sql.gz when FILE_STORAGE_MODE=s3; skip when local."""
    if settings.file_storage_mode != "s3":
        logger.info("FILE_STORAGE_MODE=local — skipping nightly DB backup upload")
        return {"skipped": True, "reason": "local storage mode"}

    parsed = urlparse(settings.database_url.replace("+asyncpg", ""))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"backups/{date_str}.sql.gz"
    with tempfile.NamedTemporaryFile(suffix=".sql") as tmp:
        cmd = [
            "pg_dump",
            "-h", parsed.hostname or "127.0.0.1",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "postgres",
            "-d", (parsed.path or "/postgres").lstrip("/"),
            "-f", tmp.name,
        ]
        env = {"PGPASSWORD": parsed.password or ""}
        subprocess.run(cmd, env=env, check=True, capture_output=True)
        with open(tmp.name, "rb") as f:
            compressed = gzip.compress(f.read())

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
    )
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=compressed)
    logger.info("Uploaded DB backup to %s", key)
    return {"uploaded": key}
