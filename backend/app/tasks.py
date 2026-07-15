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
    """pg_dump -> gzip -> S3 backups/YYYY-MM-DD.sql.gz; keep the newest 14, delete older."""
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

    from app.storage import S3Storage

    s3 = S3Storage()
    s3.client.put_object(Bucket=s3.bucket, Key=key, Body=compressed)
    logger.info("Uploaded DB backup to %s", key)

    deleted = _apply_backup_retention(s3, ist_now)
    return {"uploaded": key, "deleted": deleted}


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
            try:
                ref_bytes = storage.get(emp.reference_selfie_key)
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
                # notify Time Office manager
                dept = (
                    await session.execute(select(Department).where(Department.code == "TIME_OFFICE"))
                ).scalar_one_or_none()
                if dept and dept.manager_employee_id:
                    title, body = template(
                        "attendance_face_mismatch",
                        f"{emp.full_name} ({emp.emp_id}) — score {att.face_match_score}",
                    )
                    await dispatcher.notify(
                        session, dept.manager_employee_id, "attendance_face_mismatch",
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


# ---------------- Phase 4 Part C: incident severity classification ----------------

async def _classify_incident_async(incident_id: str) -> dict:
    from app import ai_core
    from app.models import Department, Employee, Incident, IncidentTimeline
    from app.notify import dispatcher, template
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
            try:
                image = get_storage().get(inc.photo_key)
            except Exception:
                pass

            prompt = (
                "Classify the severity of this factory incident.\n"
                f"Category: {inc.category}\nDescription: {inc.description or '(none)'}\n"
                'Respond ONLY with JSON {"severity": "normal"|"high"|"critical", '
                '"reason": one short English sentence}.\n'
                "critical = immediate danger to life, fire, major machine failure stopping production; "
                "high = significant risk or damage needing urgent action; normal = routine issue."
            )
            try:
                if image:
                    result = await ai_core.vision_json(prompt, image)
                else:
                    result = await ai_core.text_json(
                        "You classify factory incident severity. Respond ONLY with valid JSON.", prompt
                    )
            except Exception as e:
                logger.warning("Severity classification failed for %s: %s", incident_id, e)
                return {"error": "ai_failed"}

            severity = str(result.get("severity", "")).lower()
            if severity not in ("normal", "high", "critical"):
                return {"error": f"invalid severity '{severity}'"}
            reason = str(result.get("reason") or "")[:300]

            inc.severity = severity
            inc.severity_reason = reason
            session.add(
                IncidentTimeline(
                    incident_id=inc.id, actor_id=None, event="ai_severity",
                    detail_json={"severity": severity, "reason": reason},
                )
            )

            if severity == "critical":
                recipients: set = set()
                dept = (
                    await session.execute(select(Department).where(Department.code == inc.department_code))
                ).scalar_one_or_none()
                if dept and dept.manager_employee_id:
                    recipients.add(dept.manager_employee_id)
                tops = (
                    (
                        await session.execute(
                            select(Employee).join(
                                Employee.role
                            ).where(Employee.is_active.is_(True))
                        )
                    )
                    .scalars()
                    .all()
                )
                for e in tops:
                    if e.role and e.role.rank <= 2:  # CGM + MD (when exists)
                        recipients.add(e.id)
                title, body = template("incident_critical", f"{inc.category} — {reason}")
                for rid in recipients:
                    await dispatcher.notify(
                        session, rid, "incident_critical", title, body, "incident", str(inc.id)
                    )

            await session.commit()

            r = _fresh_redis()
            try:
                uk = f"ai:usage:{now_ist().date().isoformat()}:severity"
                if r.incr(uk) == 1:
                    r.expire(uk, 8 * 86400)
            finally:
                r.close()
            return {"severity": severity, "reason": reason}
    finally:
        await engine.dispose()


@celery.task(name="app.tasks.classify_incident_severity")
def classify_incident_severity(incident_id: str) -> dict:
    return asyncio.run(_classify_incident_async(incident_id))


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
            .where(Attendance.date == target_date)
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
            .where(safunc.date(FormSubmission.created_at) == target_date)
            .group_by(FormSubmission.department_code)
        )
    ).all()
    subs = {dc: n for dc, n in sub_rows}

    opened = (
        await session.execute(
            select(safunc.count()).select_from(Incident).where(safunc.date(Incident.created_at) == target_date)
        )
    ).scalar() or 0
    resolved = (
        await session.execute(
            select(safunc.count()).select_from(Incident).where(safunc.date(Incident.resolved_at) == target_date)
        )
    ).scalar() or 0
    critical_rows = (
        (
            await session.execute(
                select(Incident).where(
                    safunc.date(Incident.created_at) == target_date, Incident.severity == "critical"
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
            .where(FormSubmission.status == "submitted")
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
                    select(Employee).where(Employee.role_code == "CGM", Employee.is_active.is_(True)).limit(1)
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

            # notify CGM + MD with presigned link
            tops = (
                (
                    await session.execute(select(Employee).where(Employee.is_active.is_(True)))
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

    yesterday = now_ist().date() - timedelta(days=1)
    result = asyncio.run(generate_report_async(yesterday))
    logger.info("Nightly report generated: %s", result)
    return result
