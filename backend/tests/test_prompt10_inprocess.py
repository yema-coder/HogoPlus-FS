"""Prompt 10 (Part D) — in-process scheduler + Celery-free production paths."""

import uuid as _uuid
from datetime import datetime, timezone

from app.scheduler import JOBS, acquire_job_lock, start_scheduler
from app.tasks import _job_lock_sync, _python_sql_dump_async, _sql_literal


def test_scheduler_jobs_registry():
    ids = [name for name, _cron, _ttl, _fn in JOBS]
    assert ids == [
        "escalation_sweep",
        "ai_suggestion_timeout_sweep",
        "punchout_reminder_sweep",
        "demo_cleanup_sweep",
        "vehicle_overstay_sweep",
        "nightly_backup",
        "nightly_report",
    ]
    # lock TTL must be shorter than the job interval so the next window can acquire
    intervals = {
        "escalation_sweep": 30 * 60,
        "ai_suggestion_timeout_sweep": 5 * 60,
        "punchout_reminder_sweep": 15 * 60,
        "demo_cleanup_sweep": 15 * 60,
        "vehicle_overstay_sweep": 60 * 60,
        "nightly_backup": 4 * 3600,
        "nightly_report": 24 * 3600,
    }
    for name, _cron, ttl, fn in JOBS:
        assert ttl < intervals[name], name
        assert callable(fn)


def test_scheduler_disabled_under_testing():
    # conftest sets TESTING=1 — the scheduler must never start inside pytest
    assert start_scheduler() is None


async def test_job_lock_single_execution_across_paths(client):
    # async lock (APScheduler path) wins, sync lock (Celery path) then skips — and
    # vice versa — guaranteeing single execution across containers/processes
    assert await acquire_job_lock("unit_job_a", 60) is True
    assert await acquire_job_lock("unit_job_a", 60) is False
    assert _job_lock_sync("unit_job_a", 60) is False

    assert _job_lock_sync("unit_job_b", 60) is True
    assert await acquire_job_lock("unit_job_b", 60) is False


def test_sql_literal_edge_cases():
    assert _sql_literal(None) == "NULL"
    assert _sql_literal(True) == "TRUE"
    assert _sql_literal(7) == "7"
    assert _sql_literal("it's") == "'it''s'"
    u = _uuid.uuid4()
    assert _sql_literal(u) == f"'{u}'"
    dt = datetime(2026, 7, 16, 21, 1, tzinfo=timezone.utc)
    assert _sql_literal(dt) == "'2026-07-16T21:01:00+00:00'"
    assert _sql_literal(["a.jpg", "b.jpg"]) == "'{\"a.jpg\",\"b.jpg\"}'"
    assert _sql_literal(b"\x01\xff") == "'\\x01ff'"


async def test_python_sql_dump_fallback(client):
    # runs against the seeded test DB — no pg_dump binary involved
    dump = (await _python_sql_dump_async()).decode()
    assert "SET session_replication_role = replica;" in dump
    assert 'INSERT INTO "employees"' in dump
    assert 'INSERT INTO "departments"' in dump
    assert dump.rstrip().endswith("SET session_replication_role = DEFAULT;")
