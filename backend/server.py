"""Uvicorn entrypoint (supervisor runs `uvicorn server:app`)."""
from app.main import app  # noqa: F401
