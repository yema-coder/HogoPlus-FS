from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.redis_client import redis_client
from app.security import get_access_or_registration_payload
from app.storage import LocalStorage, get_storage

router = APIRouter(tags=["files"])

MAX_SIZE = 10 * 1024 * 1024
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "m4a", "mp3", "pdf"}
EXT_ALIASES = {"jpeg": "jpg"}
UPLOADS_PER_HOUR = 20


def _magic_ok(ext: str, content: bytes) -> bool:
    """Validate file content against magic bytes — extension alone is not trusted."""
    if ext in ("jpg", "jpeg"):
        return content.startswith(b"\xff\xd8\xff")
    if ext == "png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "webp":
        return len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if ext == "m4a":
        return len(content) > 11 and content[4:8] == b"ftyp"
    if ext == "mp3":
        return content.startswith(b"ID3") or (
            len(content) > 1 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0
        )
    if ext == "pdf":
        return content.startswith(b"%PDF")
    return False


@router.post("/files/upload")
async def upload_file(
    file: UploadFile,
    token_payload: dict = Depends(get_access_or_registration_payload),
):
    """Requires a full access token OR a 15-min registration token
    (self-registration selfie is uploaded before an account exists)."""
    principal = token_payload.get("jti") or token_payload.get("sub")
    rate_key = f"upload:rate:{principal}"
    count = await redis_client.incr(rate_key)
    if count == 1:
        await redis_client.expire(rate_key, 3600)
    if count > UPLOADS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Upload limit reached (20 per hour)")

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed. Allowed: {sorted(ALLOWED_EXT)}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    if not _magic_ok(ext, content):
        raise HTTPException(status_code=400, detail=f"File content does not match .{ext} format")
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
