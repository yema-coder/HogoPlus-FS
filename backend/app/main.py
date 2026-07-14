import logging
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    admin,
    ai,
    attendance,
    auth,
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
    return {"status": "healthy"}


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

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    # warm the local embedding model once at startup (non-blocking)
    if not os.environ.get("TESTING"):
        import asyncio

        from starlette.concurrency import run_in_threadpool

        from app.embeddings import get_model

        asyncio.get_event_loop().create_task(run_in_threadpool(get_model))
