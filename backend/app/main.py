import logging
import os
from pathlib import Path

logger = logging.getLogger("hogo.main")

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    admin,
    ai,
    attendance,
    auth,
    dashboard,
    departments,
    files,
    forms,
    home,
    incidents,
    notifications,
    shifts,
    vehicles,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(title="Hogo Plus-FS API", version="1.0.0")

api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {"service": "hogo-plus-fs", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "healthy", "db_seeded": getattr(app.state, "db_seeded", None)}


api.include_router(auth.router)
api.include_router(departments.router)
api.include_router(forms.router)
api.include_router(incidents.router)
api.include_router(attendance.router)
api.include_router(shifts.router)
api.include_router(files.router)
api.include_router(admin.router)
api.include_router(notifications.router)
api.include_router(ai.router)
api.include_router(dashboard.router)
api.include_router(home.router)
api.include_router(vehicles.router)

app.include_router(api)

# MD Command Center SPA — built by /app/webdash, served at /api/dash (the ingress only
# forwards /api/* to this service; /dashboard redirects there for convenience).
WEBDASH_DIST = Path(__file__).resolve().parent.parent / "webdash_dist"
if WEBDASH_DIST.exists():
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/api/dash/assets", StaticFiles(directory=WEBDASH_DIST / "assets"), name="dash-assets")

    @app.get("/api/dash{path:path}")
    async def dashboard_spa(path: str):  # SPA fallback for client routes
        candidate = (WEBDASH_DIST / path.lstrip("/")).resolve()
        if path and candidate.is_file() and str(candidate).startswith(str(WEBDASH_DIST)):
            return FileResponse(candidate)
        return FileResponse(WEBDASH_DIST / "index.html")

    @app.get("/dashboard{path:path}")
    async def dashboard_redirect(path: str):
        return RedirectResponse(f"/api/dash{path or '/'}")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prompt 18: compress JSON payloads (dashboard aggregates ~17KB → ~4KB on slow links)
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.on_event("startup")
async def _startup():
    # Build/config guard: fail fast if any env value still contains an unfilled
    # "<placeholder>" (e.g. env.sample's S3_ENDPOINT_URL "<account-id>"), which would
    # otherwise crash boto3/DB clients with an opaque error deep inside a request.
    if not os.environ.get("TESTING"):
        import re as _re

        _unfilled = sorted(
            k for k, v in settings.model_dump().items()
            if isinstance(v, str) and _re.search(r"<[^>]+>", v)
        )
        if _unfilled:
            raise RuntimeError(
                "Refusing to start — these env vars still contain placeholder "
                f"values (edit your .env): {', '.join(_unfilled)}"
            )
        # ---- OTP fail-fast guard (Prompt 21 Bug 1) -------------------------------
        # If OTP config never reached the container (compose env_file not applied /
        # .env parse poisoned by quotes, CRLF or inline comments), CRASH LOUDLY at
        # boot instead of silently falling back to demo OTP.
        _otp_mode = settings.otp_mode.strip().lower()
        if not _otp_mode:
            raise RuntimeError(
                "OTP_MODE_NOT_SET: OTP_MODE is missing or empty in the container "
                "environment — the .env values are NOT reaching the app. Check "
                "docker-compose env_file mapping and .env syntax (unbalanced quotes, "
                "CRLF line endings, inline comments, missing newline before appended "
                "lines). Refusing to start rather than silently running demo OTP."
            )
        if _otp_mode not in ("demo", "smsgatewayhub", "msg91", "whatsapp"):
            raise RuntimeError(
                f"OTP_MODE_INVALID: OTP_MODE={settings.otp_mode!r} is not one of "
                "demo | smsgatewayhub | msg91 | whatsapp."
            )
        if _otp_mode == "smsgatewayhub":
            _missing = [name for name, val in (
                ("SMSGATEWAYHUB_API_KEY", settings.smsgatewayhub_api_key),
                ("SMSGATEWAYHUB_SENDER_ID", settings.smsgatewayhub_sender_id),
                ("SMSGATEWAYHUB_DLT_TEMPLATE_ID", settings.smsgatewayhub_dlt_template_id),
                ("OTP_TEMPLATE_TEXT", settings.otp_template_text),
            ) if not val.strip()]
            if _missing:
                raise RuntimeError(
                    "SMSGATEWAYHUB_CONFIG_MISSING: OTP_MODE=smsgatewayhub but these "
                    f"env vars are empty: {', '.join(_missing)}"
                )
            if "{#var#}" not in settings.otp_template_text:
                raise RuntimeError(
                    "OTP_TEMPLATE_TEXT_INVALID: no {#var#} placeholder found — the "
                    "text must be the EXACT DLT-approved template."
                )
            if not settings.smsgatewayhub_entity_id.strip():
                logger.warning(
                    "SMSGATEWAYHUB_ENTITY_ID is BLANK — SMSGatewayHub's API guide "
                    "requires EntityId (DLT Principal Entity ID) for India DLT "
                    "traffic; sends may be rejected or silently dropped by DLT scrubbing."
                )
    # Startup visibility (Prompt 21 Bug 1): ONE line showing the effective OTP config.
    from app.otp import mask_key as _mask_key

    logger.info(
        "OTP CONFIG: mode=%s demo_otp_enabled=%s sender_id=%s api_key=%s entity_id=%s "
        "template_len=%d allow_new_registration=%s rate_limit=%d/%dmin cooldown=%ds",
        settings.otp_mode or "(unset)", settings.demo_otp_enabled,
        settings.smsgatewayhub_sender_id or "(unset)",
        _mask_key(settings.smsgatewayhub_api_key),
        "set" if settings.smsgatewayhub_entity_id else "BLANK",
        len(settings.otp_template_text), settings.allow_new_registration,
        settings.otp_max_per_window, settings.otp_window_minutes,
        settings.otp_resend_cooldown_seconds,
    )
    # AI cost isolation: production must run on the factory's own OpenAI account.
    from app import ai_core as _ai_core

    _key, _provider, _model = _ai_core.llm_route()
    logger.info(
        "AI CONFIG: llm=%s/%s stt=whisper-1 tts=%s key_source=%s",
        _provider, _model, _ai_core.TTS_MODEL,
        "openai-dedicated" if settings.openai_api_key
        else ("emergent-universal-FALLBACK" if settings.emergent_llm_key else "MISSING"),
    )
    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not set — AI is running on the Emergent universal key "
            "(sandbox fallback). Set OPENAI_API_KEY in production secrets for "
            "dedicated billing and cost isolation."
        )
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.state.db_seeded = None
    # Redis write probe: a read-only Upstash token must fail loudly at boot.
    if not os.environ.get("TESTING"):
        from app.redis_client import redis_write_probe

        await redis_write_probe()
    # DB integrity check: pod recycles have wiped PostgreSQL before. Never auto-restore.
    try:
        from sqlalchemy import text as sqltext

        from app.database import engine

        async with engine.connect() as conn:
            count = (await conn.execute(sqltext("SELECT count(*) FROM employees"))).scalar()
        app.state.db_seeded = bool(count)
        if not count:
            raise RuntimeError("employees table empty")
    except Exception as e:
        app.state.db_seeded = False
        logger.critical("DATABASE APPEARS EMPTY OR UNREACHABLE (%s) — manual restore needed: see README DISASTER RECOVERY", e)
        try:
            from sqlalchemy import select

            from app.database import SessionLocal
            from app.models import Employee
            from app.notify import dispatcher

            async with SessionLocal() as session:
                cgms = (
                    (await session.execute(select(Employee).where(Employee.role_code == "CGM"))).scalars().all()
                )
                for c in cgms:
                    await dispatcher.notify(
                        session, c.id, "system",
                        {"en": "Database appears empty — restore needed", "hi": "डेटाबेस खाली दिख रहा है — रिस्टोर आवश्यक", "mr": "डेटाबेस रिकामा दिसतो — रिस्टोर आवश्यक"},
                        {"en": "Run scripts/restore_latest.py (see README)", "hi": "scripts/restore_latest.py चलाएँ (README देखें)", "mr": "scripts/restore_latest.py चालवा (README पहा)"},
                        None, None,
                    )
                await session.commit()
        except Exception:
            pass  # if the DB is gone we cannot persist a notification — the CRITICAL log stands
    # In-process scheduler (Prompt 9/10 root cause: production runs no Celery
    # beat/worker) — backups, sweeps, reminders and reports run inside the API
    # process; Redis NX locks prevent duplicate runs across containers.
    if not os.environ.get("TESTING"):
        from app.scheduler import start_scheduler

        start_scheduler()

        # Prompt 18: keep MD dashboard aggregates hot — first paint is then
        # cache-served (~0.6s) instead of a 10-query cold fanout (~5s on Neon).
        async def _overview_warmer():
            import asyncio as _asyncio

            from app.routers.dashboard import warm_overview_cache

            while True:
                try:
                    await warm_overview_cache()
                except Exception:
                    logging.getLogger("hogo").warning("overview cache warm failed", exc_info=True)
                await _asyncio.sleep(15)

        import asyncio as _asyncio

        _asyncio.get_running_loop().create_task(_overview_warmer())
    # NOTE (Prompt 7 launch fix): the embedding model is intentionally NOT warmed at
    # startup. Eager warm-up put ~500MB of ONNX weights into the API process at boot,
    # which OOM-crash-looped 1Gi production containers (backend RSS ~700MB + celery).
    # app.embeddings.get_model() stays a lazy thread-safe singleton — the model loads
    # on the FIRST RAG/embedding call and is cached for the process lifetime.
