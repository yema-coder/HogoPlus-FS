"""In-process scheduler — PRODUCTION runs NO Celery beat/worker, so every scheduled
job executes inside the API process via APScheduler (AsyncIOScheduler).

Sandbox and production share the same Neon DB + Upstash Redis, so every run first
takes a Redis NX lock (jobs:lock:<name>) guaranteeing a SINGLE execution across all
containers. The Celery beat tasks take the same locks, so even if beat runs in the
sandbox nothing executes twice.
"""
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("hogo.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def acquire_job_lock(name: str, ttl_seconds: int) -> bool:
    from app.redis_client import redis_client

    ok = await redis_client.set(f"jobs:lock:{name}", "1", nx=True, ex=ttl_seconds)
    return bool(ok)


async def _run(name: str, ttl_seconds: int, fn) -> None:
    try:
        if not await acquire_job_lock(name, ttl_seconds):
            logger.info("scheduler: %s skipped — already executed by another container", name)
            return
    except Exception:
        # Redis briefly unreachable must not stop critical jobs — run anyway
        logger.exception("scheduler: %s lock check failed — running without lock", name)
    try:
        result = await fn()
        logger.info("scheduler: %s done → %s", name, result)
    except Exception:
        logger.exception("scheduler: %s FAILED", name)


async def _escalation():
    from app.tasks import _sweep_async

    return await _sweep_async()


async def _ai_timeout():
    from app.tasks import _ai_timeout_sweep_async

    return await _ai_timeout_sweep_async()


async def _punchout():
    from app.tasks import _punchout_reminder_async

    return await _punchout_reminder_async()


async def _backup():
    from starlette.concurrency import run_in_threadpool

    from app.tasks import run_backup_sync

    return await run_in_threadpool(run_backup_sync)


async def _report():
    from datetime import timedelta

    from app.shift_logic import now_ist
    from app.tasks import generate_report_async

    return await generate_report_async(now_ist().date() - timedelta(days=1))


# (job id, UTC cron kwargs, redis lock TTL seconds, coroutine)
# Mirrors the legacy Celery beat schedule exactly.
JOBS = [
    ("escalation_sweep", {"minute": "*/30"}, 25 * 60, _escalation),
    ("ai_suggestion_timeout_sweep", {"minute": "*/5"}, 4 * 60, _ai_timeout),
    ("punchout_reminder_sweep", {"minute": "*/15"}, 12 * 60, _punchout),
    ("nightly_backup", {"hour": "3,7,11,15,19,23", "minute": "0"}, 210 * 60, _backup),
    ("nightly_report", {"hour": "0", "minute": "30"}, 20 * 3600, _report),
]


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the in-process scheduler exactly once per container.
    Disabled under TESTING or DISABLE_SCHEDULER=true."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if os.environ.get("TESTING") or os.environ.get("DISABLE_SCHEDULER", "").lower() == "true":
        logger.info("scheduler: disabled (TESTING/DISABLE_SCHEDULER)")
        return None
    sched = AsyncIOScheduler(timezone="UTC")
    for name, cron, ttl, fn in JOBS:
        sched.add_job(
            _run,
            CronTrigger(timezone="UTC", **cron),
            args=[name, ttl, fn],
            id=name,
            name=name,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
    sched.start()
    _scheduler = sched
    for job in sched.get_jobs():
        logger.info("scheduler: registered %s → next run %s", job.id, job.next_run_time)
    logger.info(
        "scheduler: %d jobs registered IN-PROCESS (no Celery dependency)", len(sched.get_jobs())
    )
    return sched
