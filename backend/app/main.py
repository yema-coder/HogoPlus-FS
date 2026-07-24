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
    incidents,
    notifications,
    shifts,
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
