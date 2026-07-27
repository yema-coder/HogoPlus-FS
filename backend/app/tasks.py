import asyncio
import gzip
import logging
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.celery_app import celery
from app.config import settings

logger = logging.getLogger("hogo.tasks")


def _session_factory():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


def _fresh_redis():
    """Sync Redis client for Celery tasks (avoids event-loop binding issues)."""
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _job_lock_sync(name: str, ttl_seconds: int) -> bool:
    """Same jobs:lock:* keys as app.scheduler — keeps Celery beat (sandbox) and the
    in-process APScheduler (all containers) from ever double-running a job."""
    r = _fresh_redis()
    try:
        return bool(r.set(f"jobs:lock:{name}", "1", nx=True, ex=ttl_seconds))
    finally:
        r.close()


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
    if not _job_lock_sync("escalation_sweep", 25 * 60):
        return {"skipped": "lock"}
    counts = asyncio.run(_sweep_async())
    logger.info("Escalation sweep done: %s", counts)
    return counts


async def _demo_cleanup_sweep_async() -> dict:
    """Purge judge-created demo records older than 60 min (seed rows spared)."""
    from app.demo_cleanup import run_demo_cleanup

    engine, sm = _session_factory()
    try:
        async with sm() as session:
            return await run_demo_cleanup(session)
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.nightly_backup")
def nightly_backup() -> dict:
    """pg_dump -> gzip -> S3 backups/YYYY-MM-DD.sql.gz; keep the newest 14, delete older."""
    if not _job_lock_sync("nightly_backup", 210 * 60):
        return {"skipped": "lock"}
    return run_backup_sync()


def run_backup_sync() -> dict:
    """pg_dump → gzip → R2 backups/YYYY-MM-DD/HHMM.sql.gz (IST clock).
    Retention: keep everything from the last 48h + the 00:30 daily for 14 days."""
    if settings.file_storage_mode != "s3":
        logger.info("FILE_STORAGE_MODE=local — skipping DB backup upload")
        return {"skipped": True, "reason": "local storage mode"}

    from app.shift_logic import now_ist

    parsed = urlparse(settings.database_url.replace("+asyncpg", ""))
    ist_now = now_ist()
    key = f"backups/{ist_now.strftime('%Y-%m-%d')}/{ist_now.strftime('%H%M')}.sql.gz"
    method = "pg_dump"
    try:
        with tempfile.NamedTemporaryFile(suffix=".sql") as tmp:
            cmd = [
                "pg_dump",
                "-h", (parsed.hostname or "127.0.0.1").replace("-pooler", ""),
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "postgres",
                "-d", (parsed.path or "/postgres").lstrip("/"),
                "-f", tmp.name,
            ]
            env = {"PGPASSWORD": parsed.password or ""}
            subprocess.run(cmd, env=env, check=True, capture_output=True)
            with open(tmp.name, "rb") as f:
                compressed = gzip.compress(f.read())
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        # production containers ship WITHOUT pg_dump — fall back to a pure-Python
        # data dump (restorable onto an alembic-migrated schema)
        detail = e.stderr.decode()[:200] if isinstance(e, subprocess.CalledProcessError) and e.stderr else str(e)
        logger.warning("pg_dump unavailable/failed (%s) — using Python SQL dump fallback", detail)
        compressed = gzip.compress(_python_sql_dump())
        method = "python"

    from app.storage import S3Storage

    s3 = S3Storage()
    s3.client.put_object(Bucket=s3.bucket, Key=key, Body=compressed)
    logger.info("Uploaded DB backup to %s (method=%s, %d bytes gz)", key, method, len(compressed))

    deleted = _apply_backup_retention(s3, ist_now)
    return {"uploaded": key, "method": method, "deleted": deleted}


def _sql_literal(v) -> str:
    """Best-effort SQL literal for the Python dump fallback."""
    import datetime as _dt
    import uuid as _uuid
    from decimal import Decimal

    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, (bytes, memoryview)):
        return "'\\x" + bytes(v).hex() + "'"
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return "'" + v.isoformat() + "'"
    if isinstance(v, _uuid.UUID):
        return "'" + str(v) + "'"
    if isinstance(v, list):  # postgres array (e.g. photos TEXT[])
        inner = ",".join(
            '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"' for x in v
        )
        return "'" + ("{" + inner + "}").replace("'", "''") + "'"
    # str covers TEXT + JSONB + vector (asyncpg returns both as str without codecs)
    return "'" + str(v).replace("'", "''") + "'"


def _python_sql_dump() -> bytes:
    return asyncio.run(_python_sql_dump_async())


async def _python_sql_dump_async() -> bytes:
    """Data-only SQL dump via asyncpg (no pg_dump binary needed). Restore procedure:
    alembic upgrade head on an empty DB, then execute this file (FKs disabled by
    session_replication_role=replica)."""
    import asyncpg

    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        tables = [
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
        ]
        out = [
            "-- HogoPlus Python fallback dump (data-only).",
            "-- Restore: alembic upgrade head on empty DB, then run this file.",
            f"-- generated {datetime.now(timezone.utc).isoformat()}",
            "SET session_replication_role = replica;",
        ]
        for t in tables:
            rows = await conn.fetch(f'SELECT * FROM "{t}"')
            if not rows:
                continue
            cols = list(rows[0].keys())
            colsql = ", ".join(f'"{c}"' for c in cols)
            for r in rows:
                vals = ", ".join(_sql_literal(r[c]) for c in cols)
                out.append(f'INSERT INTO "{t}" ({colsql}) VALUES ({vals});')
        out.append("SET session_replication_role = DEFAULT;")
        return "\n".join(out).encode()
    finally:
        await conn.close()


def _parse_backup_key(key: str):
    """→ (datetime IST-naive, is_daily) or None. Supports backups/YYYY-MM-DD/HHMM.sql.gz
    and the legacy backups/YYYY-MM-DD.sql.gz (treated as the daily)."""
    import re as _re

    m = _re.match(r"^backups/(\d{4}-\d{2}-\d{2})/(\d{2})(\d{2})\.sql\.gz$", key)
    if m:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
        return dt, (m.group(2), m.group(3)) == ("00", "30")
    m = _re.match(r"^backups/(\d{4}-\d{2}-\d{2})\.sql\.gz$", key)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d"), True
    return None


def _apply_backup_retention(s3, ist_now) -> list[str]:
    resp = s3.client.list_objects_v2(Bucket=s3.bucket, Prefix="backups/")
    now_naive = ist_now.replace(tzinfo=None)
    deleted = []
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        parsed = _parse_backup_key(key)
        if parsed is None:
            continue  # unknown format — never delete blindly
        dt, is_daily = parsed
        age_h = (now_naive - dt).total_seconds() / 3600
        keep = age_h <= 48 or (is_daily and age_h <= 14 * 24)
        if not keep:
            s3.client.delete_object(Bucket=s3.bucket, Key=key)
            deleted.append(key)
    if deleted:
        logger.info("Backup retention: deleted %s object(s)", len(deleted))
    return deleted


# ---------------- Phase 4 Part B: face verification ----------------

async def _verify_face_async(attendance_id: str) -> dict:
    from app.audit import write_audit
    from app.aws import RekognitionUnavailable, compare_faces
    from app.models import Attendance, Department, Employee
    from app.notify import dispatcher, template
    from app.shift_logic import now_ist
    from app.storage import get_storage
    from sqlalchemy import select

    engine, sm = _session_factory()
    try:
        async with sm() as session:
            att = await session.get(Attendance, attendance_id)
            if att is None:
                return {"error": "attendance not found"}
            emp = await session.get(Employee, att.employee_id)
            if emp is None:
                return {"error": "employee not found"}

            # bootstrap rule: first punch selfie becomes the reference (seeded employees).
            # It lands in the Time Office queue as 'reference_bootstrap' — a human must
            # confirm the reference face belongs to this employee.
            if not emp.reference_selfie_key:
                emp.reference_selfie_key = att.selfie_key
                emp.reference_selfie_set_at = datetime.now(timezone.utc)
                att.verification_level = "flagged"
                att.flagged_reason = "reference_bootstrap"
                await write_audit(
                    session, None, "employee.reference_selfie_bootstrap", "employee",
                    str(emp.id), {"attendance_id": str(att.id), "selfie_key": att.selfie_key},
                )
                await session.commit()
                logger.info("Face reference bootstrapped for %s", emp.emp_id)
                return {"bootstrap": True, "employee": emp.emp_id}

            storage = get_storage()

            # GHOST-REFERENCE HARDENING (2026-07-27 field failure): if the reference
            # OBJECT is gone from storage (NoSuchKey — e.g. lost during the local-
            # storage fallback era), clear the stale key and treat THIS punch as a
            # supervised re-bootstrap instead of failing silently with a NULL score.
            def _read_or_none(key: str) -> bytes | None:
                """bytes, or None when the object is DEFINITIVELY missing; raises otherwise."""
                try:
                    return storage.get(key)
                except FileNotFoundError:
                    return None
                except Exception as e:
                    code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
                    if code in ("NoSuchKey", "404"):
                        return None
                    raise

            try:
                ref_bytes = _read_or_none(emp.reference_selfie_key)
            except Exception as e:
                logger.warning("Face verification could not read reference for %s: %s", att.id, e)
                return {"error": "selfie_read_failed"}
            if ref_bytes is None:
                stale_key = emp.reference_selfie_key
                emp.reference_selfie_key = att.selfie_key
                emp.reference_selfie_set_at = datetime.now(timezone.utc)
                att.verification_level = "flagged"
                att.flagged_reason = "reference_bootstrap"
                await write_audit(
                    session, None, "employee.reference_selfie_rebootstrap", "employee",
                    str(emp.id),
                    {"attendance_id": str(att.id), "stale_key": stale_key, "selfie_key": att.selfie_key},
                )
                await session.commit()
                logger.warning(
                    "Stale face reference for %s (missing object %s) — re-bootstrapped from this punch",
                    emp.emp_id, stale_key,
                )
                return {"rebootstrap": True, "employee": emp.emp_id, "stale_key": stale_key}

            try:
                new_bytes = storage.get(att.selfie_key)
                score = compare_faces(ref_bytes, new_bytes)
            except RekognitionUnavailable as e:
                r = _fresh_redis()
                try:
                    fk = f"rekognition:failures:{now_ist().date().isoformat()}"
                    r.incr(fk)
                    r.expire(fk, 8 * 86400)
                finally:
                    r.close()
                logger.warning("Face verification unavailable for %s: %s", att.id, e)
                return {"error": "rekognition_unavailable"}  # face_verified stays null — never flag for infra failure
            except Exception as e:
                logger.warning("Face verification could not read selfies for %s: %s", att.id, e)
                return {"error": "selfie_read_failed"}

            att.face_match_score = round(score, 2)
            detail = {"score": att.face_match_score}
            if score >= 90:
                att.face_verified = True
            elif score < 80:
                att.face_verified = False
                att.verification_level = "flagged"
                att.flagged_reason = "face_mismatch"
                # notify Time Office manager (class-aware: demo punches → Demo TO manager)
                from app.demo import resolve_dept_manager_id

                dept = (
                    await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
                ).scalar_one_or_none()
                to_mgr_id = await resolve_dept_manager_id(session, dept, emp.is_demo)
                if to_mgr_id:
                    title, body = template(
                        "attendance_face_mismatch",
                        f"{emp.full_name} ({emp.emp_id}) — score {att.face_match_score}",
                    )
                    await dispatcher.notify(
                        session, to_mgr_id, "attendance_face_mismatch",
                        title, body, "attendance", str(att.id),
                    )
            # 80-89: borderline — face_verified stays null, verification_level unchanged, score stored
            await write_audit(
                session, None, "attendance.face_verified", "attendance", str(att.id), detail
            )
            await session.commit()
            return {"score": att.face_match_score, "face_verified": att.face_verified}
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.verify_face")
def verify_face_task(attendance_id: str) -> dict:
    return asyncio.run(_verify_face_async(attendance_id))


async def run_face_verification_background(attendance_id: str) -> None:
    """In-process face verification (FastAPI background task) — production containers
    run no Celery worker. Never raises; outcome always logged."""
    try:
        out = await _verify_face_async(attendance_id)
        logger.info("Face verification attendance/%s → %s", attendance_id, out)
    except Exception:
        logger.exception("Face verification FAILED for attendance %s", attendance_id)


# ---------------- Phase 4 Part C: incident severity classification ----------------

async def _classify_incident_async(incident_id: str) -> dict:
    """Full AI classification: suggest category + department + severity with
    confidence. Stored as ai_suggested_* — routing/notifications fire only when
    the worker confirms (or the 10-minute timeout auto-applies)."""
    from app import ai_core
    from app.models import Department, Incident, IncidentTimeline
    from app.shift_logic import now_ist
    from app.storage import get_storage
    from sqlalchemy import select

    engine, sm = _session_factory()
    try:
        async with sm() as session:
            inc = await session.get(Incident, incident_id)
            if inc is None:
                return {"error": "incident not found"}

            image = None
            if inc.photo_key:
                try:
                    image = get_storage().get(inc.photo_key)
                except Exception as e:
                    logger.warning(
                        "classification could not fetch photo %s for incident %s: %s",
                        inc.photo_key, incident_id, e,
                    )

            transcript = ""
            if inc.voice_note_key:
                try:
                    audio_bytes = get_storage().get(inc.voice_note_key)
                    ext = inc.voice_note_key.rsplit(".", 1)[-1] if "." in inc.voice_note_key else "m4a"
                    transcript, _lang = await ai_core.transcribe_audio(audio_bytes, ext)
                except Exception as e:
                    logger.warning("Voice transcript failed for %s: %s", incident_id, e)

            depts = (
                await session.execute(select(Department).where(Department.is_active.is_(True)))
            ).scalars().all()
            dept_codes = [d.code for d in depts]
            prompt = (
                "Classify this factory incident report.\n"
                f"Worker description: {inc.description or '(none)'}\n"
                f"Voice note transcript: {transcript or '(none)'}\n"
                f"Departments: {', '.join(dept_codes)}\n"
                'Respond ONLY with JSON {"category": "safety"|"fire"|"machine_breakdown"|"injury"|'
                '"electrical"|"water_leakage"|"security"|"other", '
                '"department_code": which department this incident is ABOUT (from the list), '
                '"severity": "normal"|"high"|"critical", '
                '"confidence": 0.0-1.0, "reason": one short English sentence}.\n'
                "critical = immediate danger to life, fire, major machine failure stopping production; "
                "high = significant risk or damage needing urgent action; normal = routine issue."
            )
            try:
                if image:
                    result = await ai_core.vision_json(prompt, image)
                else:
                    result = await ai_core.text_json(
                        "You classify factory incident reports. Respond ONLY with valid JSON.", prompt
                    )
            except Exception as e:
                logger.warning("Incident classification failed for %s: %s", incident_id, e)
                return {"error": "ai_failed"}

            category = str(result.get("category", "")).lower()
            if category not in ("safety", "fire", "machine_breakdown", "injury",
                                "electrical", "water_leakage", "security", "other"):
                category = "other"
            dept_code = str(result.get("department_code", ""))
            if dept_code not in dept_codes:
                dept_code = inc.department_code
            severity = str(result.get("severity", "")).lower()
            if severity not in ("normal", "high", "critical"):
                severity = "normal"
            try:
                confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
            reason = str(result.get("reason") or "")[:300]

            inc.ai_suggested_category = category
            inc.ai_suggested_department = dept_code
            inc.ai_suggested_severity = severity
            inc.ai_confidence = confidence
            inc.ai_suggested_at = now_ist()
            inc.severity_reason = reason
            session.add(
                IncidentTimeline(
                    incident_id=inc.id, actor_id=None, event="ai_suggestion",
                    detail_json={"category": category, "department_code": dept_code,
                                 "severity": severity, "confidence": confidence, "reason": reason},
                )
            )
            await session.commit()

            r = _fresh_redis()
            try:
                from app.ai_core import usage_key_prefix

                uk = f"{usage_key_prefix(inc.is_demo)}:{now_ist().date().isoformat()}:classify"
                if r.incr(uk) == 1:
                    r.expire(uk, 8 * 86400)
            finally:
                r.close()
            return {"category": category, "department_code": dept_code,
                    "severity": severity, "confidence": confidence}
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.classify_incident_severity")
def classify_incident_severity(incident_id: str) -> dict:
    return asyncio.run(_classify_incident_async(incident_id))


# ---------------- AI-suggestion timeout auto-apply ----------------

AI_CONFIRM_TIMEOUT_MIN = 10


async def _ai_timeout_sweep_async() -> dict:
    """Never let an incident sit unrouted: auto-apply the AI suggestion after
    10 minutes without worker confirmation (confirmed_by='ai_timeout')."""
    from datetime import timedelta

    from app.models import Incident
    from app.routers.incidents import apply_incident_routing
    from app.shift_logic import now_ist
    from sqlalchemy import select

    engine, sm = _session_factory()
    applied = 0
    try:
        async with sm() as session:
            cutoff = now_ist() - timedelta(minutes=AI_CONFIRM_TIMEOUT_MIN)
            rows = (
                await session.execute(
                    select(Incident).where(
                        Incident.ai_confirmed_by.is_(None),
                        Incident.ai_suggested_at.isnot(None),
                        Incident.ai_suggested_at < cutoff,
                    )
                )
            ).scalars().all()
            for inc in rows:
                await apply_incident_routing(
                    session, inc,
                    inc.ai_suggested_category or inc.category,
                    inc.ai_suggested_department or inc.department_code,
                    inc.ai_suggested_severity or inc.severity,
                    "ai_timeout",
                )
                applied += 1
            await session.commit()
    finally:
        await engine.dispose()
    return {"applied": applied}


@celery.task(name="app.tasks.ai_suggestion_timeout_sweep")
def ai_suggestion_timeout_sweep() -> dict:
    if not _job_lock_sync("ai_suggestion_timeout_sweep", 4 * 60):
        return {"skipped": "lock"}
    return asyncio.run(_ai_timeout_sweep_async())


# ---------------- Opportunistic ANPR (DetectText → Universal-Key vision fallback) ----------------

from app.anpr import extract_plate  # noqa: E402  (re-export for back-compat)


async def _detect_plate_async(kind: str, record_id: str) -> dict:
    """ANPR pipeline for a record's photos: Rekognition DetectText + confusable-aware
    Indian-plate extraction; incidents additionally fall back to Universal-Key vision.
    The outcome is ALWAYS stored on incidents (plate_status/confidence/source/reason)
    and ALWAYS logged at INFO level."""
    from starlette.concurrency import run_in_threadpool

    from app.anpr import extract_plate_from_lines, llm_plate_fallback
    from app.aws import detect_text
    from app.models import FormSubmission, Incident
    from app.shift_logic import now_ist
    from app.storage import get_storage

    engine, sm = _session_factory()
    calls = 0
    vision_calls = 0
    try:
        async with sm() as session:
            keys: list[str] = []
            if kind == "incident":
                rec = await session.get(Incident, record_id)
                if rec is None:
                    return {"error": "not found"}
                keys = [k for k in (rec.photo_key, rec.resolution_photo_key) if k]
            elif kind == "submission":
                rec = await session.get(FormSubmission, record_id)
                if rec is None:
                    return {"error": "not found"}
                keys = list(rec.photos or [])
            else:
                return {"error": f"unknown kind {kind}"}

            plates: list[str] = []
            best: tuple[str | None, float | None, str | None] = (None, None, None)
            any_text = False
            any_call_ok = False
            for key in keys:
                try:
                    img = get_storage().get(key)
                    lines = await run_in_threadpool(detect_text, img)
                    calls += 1
                    any_call_ok = True
                except Exception as e:
                    logger.warning("DetectText failed for %s/%s: %s", kind, key, e)
                    continue
                if lines:
                    any_text = True
                plate, conf = extract_plate_from_lines(lines)
                if plate:
                    if best[0] is None:
                        best = (plate, conf, "rekognition")
                    if plate not in plates:
                        plates.append(plate)

            # accuracy over cost: incidents with no valid DetectText plate get a
            # Universal-Key vision second opinion on the primary photo
            if kind == "incident" and best[0] is None and keys:
                try:
                    img = get_storage().get(keys[0])
                    plate, conf = await llm_plate_fallback(img)
                    vision_calls += 1
                    any_call_ok = True
                    if plate:
                        best = (plate, conf, "llm_vision")
                        plates.append(plate)
                except Exception as e:
                    logger.warning("ANPR vision fallback failed for %s/%s: %s", kind, record_id, e)

            if kind == "incident":
                if best[0]:
                    rec.detected_plate, rec.plate_confidence, rec.plate_source = best
                    rec.plate_status = "detected"
                    rec.plate_reason = None
                else:
                    rec.plate_status = "not_detected"
                    if not any_call_ok:
                        rec.plate_reason = "detection_failed"
                    elif any_text:
                        rec.plate_reason = "no_valid_plate"
                    else:
                        rec.plate_reason = "no_text_found"
                await session.commit()
            elif plates:
                rec.detected_plates = plates
                await session.commit()

            if calls or vision_calls:
                r = _fresh_redis()
                try:
                    from app.ai_core import usage_key_prefix

                    day = now_ist().date().isoformat()
                    prefix = usage_key_prefix(bool(rec.is_demo))
                    if calls:
                        uk = f"{prefix}:{day}:detect_text"
                        if r.incrby(uk, calls) == calls:
                            r.expire(uk, 8 * 86400)
                    if vision_calls:
                        vk = f"{prefix}:{day}:anpr_vision"
                        if r.incrby(vk, vision_calls) == vision_calls:
                            r.expire(vk, 8 * 86400)
                finally:
                    r.close()

            outcome = {
                "plates": plates,
                "detect_text_calls": calls,
                "vision_calls": vision_calls,
            }
            if kind == "incident":
                outcome.update({
                    "plate_status": rec.plate_status,
                    "confidence": rec.plate_confidence,
                    "source": rec.plate_source,
                    "reason": rec.plate_reason,
                })
                logger.info(
                    "ANPR incident/%s → status=%s plate=%s conf=%s source=%s reason=%s "
                    "detect_text_calls=%d vision_calls=%d",
                    record_id, rec.plate_status, rec.detected_plate, rec.plate_confidence,
                    rec.plate_source, rec.plate_reason, calls, vision_calls,
                )
            else:
                logger.info(
                    "ANPR submission/%s → plates=%s detect_text_calls=%d",
                    record_id, plates, calls,
                )
            return outcome
    finally:
        await engine.dispose()


async def run_incident_ai_background(incident_id: str, with_plate: bool) -> None:
    """In-process incident AI (ANPR + classification) as a FastAPI background task.
    Production containers run NO Celery worker — this must never depend on a broker.
    ANPR runs FIRST: the plate result is the product; classification LLM is slower."""
    if with_plate:
        try:
            await _detect_plate_async("incident", incident_id)
        except Exception:
            logger.exception("ANPR pipeline failed for incident %s", incident_id)
    try:
        await _classify_incident_async(incident_id)
    except Exception:
        logger.exception("incident classification failed for %s", incident_id)


async def run_plate_detection_background(kind: str, record_id: str) -> None:
    """In-process ANPR only (form submissions / resolution photos)."""
    try:
        await _detect_plate_async(kind, record_id)
    except Exception:
        logger.exception("ANPR pipeline failed for %s %s", kind, record_id)


@celery.task(name="app.tasks.detect_plate")
def detect_plate_task(kind: str, record_id: str) -> dict:
    return asyncio.run(_detect_plate_async(kind, record_id))


# ---------------- Punch-out reminder ----------------

async def _punchout_reminder_async(now=None) -> dict:
    """Every 15 min: punched-in employees whose shift ended >15 min ago with no
    punch-out get ONE reminder per day (redis SETNX guard)."""
    from datetime import datetime as dt, timedelta

    from app.models import Attendance, Employee
    from app.notify import dispatcher, template
    from app.shift_logic import IST, get_shift, now_ist, resolve_shift_code
    from sqlalchemy import select

    engine, sm = _session_factory()
    sent = 0
    try:
        now = now or now_ist()
        today = now.date()
        async with sm() as session:
            rows = (
                await session.execute(
                    select(Attendance, Employee)
                    .join(Employee, Attendance.employee_id == Employee.id)
                    .where(Attendance.date == today, Attendance.punch_out_at.is_(None))
                )
            ).all()
            r = _fresh_redis()
            try:
                for att, emp in rows:
                    shift_code = await resolve_shift_code(session, emp.id, today)
                    shift = await get_shift(session, shift_code) if shift_code else None
                    if shift is None:
                        continue
                    end_dt = dt.combine(today, shift.end_time, tzinfo=IST)
                    if shift.end_time < shift.start_time:  # overnight shift ends next day
                        end_dt += timedelta(days=1)
                    if now < end_dt + timedelta(minutes=15):
                        continue
                    guard = f"punchout_reminder:{emp.id}:{today.isoformat()}"
                    if not r.set(guard, "1", nx=True, ex=86400):
                        continue  # already reminded today
                    title, body = template("punchout_reminder")
                    await dispatcher.notify(
                        session, emp.id, "punchout_reminder", title, body,
                        "attendance", str(att.id),
                    )
                    sent += 1
            finally:
                r.close()
            await session.commit()
    finally:
        await engine.dispose()
    return {"sent": sent}


@celery.task(name="app.tasks.punchout_reminder_sweep")
def punchout_reminder_sweep() -> dict:
    if not _job_lock_sync("punchout_reminder_sweep", 12 * 60):
        return {"skipped": "lock"}
    return asyncio.run(_punchout_reminder_async())


# ---------------- Phase 4 Part C: SOP ingestion (RAG) ----------------

def _chunk_page(text: str, target_chars: int = 3200, overlap_chars: int = 320) -> list[str]:
    """~800-token chunks (≈4 chars/token) with overlap, split on word boundaries."""
    words = text.split()
    if not words:
        return []
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= target_chars:
            chunks.append(" ".join(cur))
            # overlap: keep tail words
            tail, tail_len = [], 0
            for tw in reversed(cur):
                tail_len += len(tw) + 1
                tail.insert(0, tw)
                if tail_len >= overlap_chars:
                    break
            cur, cur_len = tail, tail_len
    if cur and (not chunks or " ".join(cur) != chunks[-1]):
        chunks.append(" ".join(cur))
    return [c.strip() for c in chunks if c.strip()]


async def _sop_ingest_async(doc_id: str) -> dict:
    import io

    from app.embeddings import embed_texts
    from app.models import SopChunk, SopDoc
    from app.storage import get_storage

    engine, sm = _session_factory()
    try:
        async with sm() as session:
            doc = await session.get(SopDoc, doc_id)
            if doc is None:
                return {"error": "doc not found"}
            try:
                from pypdf import PdfReader

                pdf_bytes = get_storage().get(doc.file_key)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                doc.page_count = len(reader.pages)
                page_chunks: list[tuple[int, int, str]] = []  # (page, chunk_index, content)
                for pno, page in enumerate(reader.pages, start=1):
                    try:
                        text = page.extract_text() or ""
                    except Exception:
                        text = ""  # no text layer → skipped (no OCR this phase)
                    for ci, chunk in enumerate(_chunk_page(text)):
                        page_chunks.append((pno, ci, chunk))

                if page_chunks:
                    vectors = embed_texts([c for _, _, c in page_chunks])
                    for (pno, ci, content), vec in zip(page_chunks, vectors):
                        session.add(
                            SopChunk(
                                doc_id=doc.id, page=pno, chunk_index=ci,
                                content=content, embedding=vec,
                            )
                        )
                doc.chunk_count = len(page_chunks)
                doc.status = "ready"
                doc.error = None
            except Exception as e:
                logger.warning("SOP ingest failed for %s: %s", doc_id, e)
                doc.status = "failed"
                doc.error = str(e)[:500]
            await session.commit()
            return {"status": doc.status, "pages": doc.page_count, "chunks": doc.chunk_count}
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.sop_ingest")
def sop_ingest_task(doc_id: str) -> dict:
    return asyncio.run(_sop_ingest_async(doc_id))


async def run_sop_ingest_background(doc_id: str) -> None:
    """In-process SOP ingest (FastAPI background task) — production has no Celery
    worker. The multilingual ONNX embedding model (~450MB RSS) is RELEASED afterwards
    so a 1Gi API container returns to steady-state; RAG queries lazily reload it."""
    from app.embeddings import release_model

    try:
        out = await _sop_ingest_async(doc_id)
        logger.info("SOP ingest %s → %s", doc_id, out)
    except Exception:
        logger.exception("SOP ingest FAILED for %s", doc_id)
    finally:
        release_model()


# ---------------- Phase 4 Part C: nightly factory report ----------------

async def _report_data(session, target_date) -> dict:
    from app.models import (
        Attendance,
        Department,
        Employee,
        FormSubmission,
        Incident,
    )
    from sqlalchemy import func as safunc, select

    depts = (await session.execute(select(Department).order_by(Department.code))).scalars().all()
    dept_names = {d.code: {"en": d.name_en, "hi": d.name_hi, "mr": d.name_mr} for d in depts}

    att_rows = (
        await session.execute(
            select(Attendance, Employee.department_code)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(Attendance.date == target_date, Attendance.is_demo.is_(False))
        )
    ).all()
    att = {d.code: {"present": 0, "late": 0, "flagged": 0} for d in depts}
    for a, dc in att_rows:
        entry = att.setdefault(dc, {"present": 0, "late": 0, "flagged": 0})
        entry["present"] += 1
        if a.is_late:
            entry["late"] += 1
        if a.verification_level == "flagged":
            entry["flagged"] += 1

    sub_rows = (
        await session.execute(
            select(FormSubmission.department_code, safunc.count())
            .where(
                safunc.date(FormSubmission.created_at) == target_date,
                FormSubmission.is_demo.is_(False),
            )
            .group_by(FormSubmission.department_code)
        )
    ).all()
    subs = {dc: n for dc, n in sub_rows}

    opened = (
        await session.execute(
            select(safunc.count()).select_from(Incident).where(
                safunc.date(Incident.created_at) == target_date, Incident.is_demo.is_(False)
            )
        )
    ).scalar() or 0
    resolved = (
        await session.execute(
            select(safunc.count()).select_from(Incident).where(
                safunc.date(Incident.resolved_at) == target_date, Incident.is_demo.is_(False)
            )
        )
    ).scalar() or 0
    critical_rows = (
        (
            await session.execute(
                select(Incident).where(
                    safunc.date(Incident.created_at) == target_date,
                    Incident.severity == "critical",
                    Incident.is_demo.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )

    # pending approvals aging: which manager, how many, oldest
    pend_rows = (
        await session.execute(
            select(
                FormSubmission.department_code,
                safunc.count(),
                safunc.min(FormSubmission.created_at),
            )
            .where(FormSubmission.status == "submitted", FormSubmission.is_demo.is_(False))
            .group_by(FormSubmission.department_code)
        )
    ).all()
    mgr_names = {}
    for d in depts:
        if d.manager_employee_id:
            mgr = await session.get(Employee, d.manager_employee_id)
            mgr_names[d.code] = mgr.full_name if mgr else None
    now = datetime.now(timezone.utc)
    approvals = [
        {
            "dept_code": dc,
            "manager": mgr_names.get(dc),
            "count": n,
            "oldest_days": max(0, (now - oldest).days) if oldest else 0,
        }
        for dc, n, oldest in pend_rows
    ]

    return {
        "date": target_date.isoformat(),
        "dept_names": dept_names,
        "attendance": [{"dept_code": d.code, **att.get(d.code, {"present": 0, "late": 0, "flagged": 0})} for d in depts],
        "submissions": [{"dept_code": d.code, "count": subs.get(d.code, 0)} for d in depts if subs.get(d.code, 0) > 0] or [],
        "incidents": {
            "opened": opened,
            "resolved": resolved,
            "critical": [{"category": c.category, "dept_code": c.department_code} for c in critical_rows],
        },
        "approvals": approvals,
    }


def _localize_report(data: dict, lang: str) -> dict:
    names = data["dept_names"]

    def nm(code: str) -> str:
        return names.get(code, {}).get(lang, code)

    return {
        "date": data["date"],
        "attendance": [{"dept": nm(r["dept_code"]), "present": r["present"], "late": r["late"], "flagged": r["flagged"]} for r in data["attendance"]],
        "submissions": [{"dept": nm(r["dept_code"]), "count": r["count"]} for r in data["submissions"]],
        "incidents": {
            "opened": data["incidents"]["opened"],
            "resolved": data["incidents"]["resolved"],
            "critical": [{"category": c["category"], "dept": nm(c["dept_code"])} for c in data["incidents"]["critical"]],
        },
        "approvals": [{"dept": nm(r["dept_code"]), "manager": r["manager"], "count": r["count"], "oldest_days": r["oldest_days"]} for r in data["approvals"]],
    }


async def generate_report_async(target_date) -> dict:
    """Build both language PDFs, upload to R2 reports/YYYY-MM-DD/, notify CGM/MD.
    Shared by the 06:00 IST beat task and POST /api/admin/generate-report."""
    from app.models import Employee
    from app.notify import dispatcher, template
    from app.report import generate_report_pdf
    from app.storage import S3Storage, get_storage
    from sqlalchemy import select

    engine, sm = _session_factory()
    try:
        async with sm() as session:
            data = await _report_data(session, target_date)

            # CGM language (mr default) + English copy
            cgm = (
                await session.execute(
                    select(Employee).where(
                        Employee.role_code == "CGM", Employee.is_active.is_(True),
                        Employee.is_demo.is_(False),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            primary_lang = (cgm.language_pref if cgm and cgm.language_pref in ("en", "hi", "mr") else "mr")
            langs = [primary_lang] if primary_lang == "en" else [primary_lang, "en"]

            storage = get_storage()
            keys = {}
            for lang in langs:
                pdf_bytes = generate_report_pdf(_localize_report(data, lang), lang)
                key = f"reports/{data['date']}/factory-report-{lang}.pdf"
                if isinstance(storage, S3Storage):
                    storage.client.put_object(Bucket=storage.bucket, Key=key, Body=pdf_bytes)
                else:  # local fallback: nested key path
                    p = storage.base / key
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(pdf_bytes)
                keys[lang] = key

            # notify real CGM + MD with presigned link (report covers real data only)
            tops = (
                (
                    await session.execute(
                        select(Employee).where(
                            Employee.is_active.is_(True), Employee.is_demo.is_(False)
                        )
                    )
                )
                .scalars()
                .all()
            )
            notified = 0
            primary_key = keys.get(primary_lang) or next(iter(keys.values()))
            link = storage.url_for(primary_key)
            for e in tops:
                if e.role and e.role.rank <= 2:
                    title, body = template("report_ready", link)
                    await dispatcher.notify(
                        session, e.id, "report_ready", title, body, "report", data["date"]
                    )
                    notified += 1
            await session.commit()
            return {"keys": keys, "notified": notified, "date": data["date"]}
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.nightly_report")
def nightly_report() -> dict:
    from app.shift_logic import now_ist

    if not _job_lock_sync("nightly_report", 20 * 3600):
        return {"skipped": "lock"}
    yesterday = now_ist().date() - timedelta(days=1)
    result = asyncio.run(generate_report_async(yesterday))
    logger.info("Nightly report generated: %s", result)
    return result
