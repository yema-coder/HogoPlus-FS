from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.config import settings
from app.storage import LocalStorage, get_storage

router = APIRouter(tags=["files"])

MAX_SIZE = 10 * 1024 * 1024
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "m4a", "mp3", "pdf"}
EXT_ALIASES = {"jpeg": "jpg"}


@router.post("/files/upload")
async def upload_file(file: UploadFile):
    """Public in phase 1: self-registration selfies are uploaded before a JWT exists.
    Keys are unguessable UUIDs."""
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed. Allowed: {sorted(ALLOWED_EXT)}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    storage = get_storage()
    key = await storage.save(content, EXT_ALIASES.get(ext, ext))
    return {"key": key, "url": storage.url_for(key)}


@router.get("/files/{key}")
async def serve_file(key: str):
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        try:
            path = storage.path_for(key)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid key")
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path)
    # S3 mode: redirect to presigned URL (24h expiry)
    return RedirectResponse(storage.url_for(key))
