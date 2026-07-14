import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import settings


class StorageAdapter(ABC):
    @abstractmethod
    async def save(self, content: bytes, ext: str) -> str: ...

    @abstractmethod
    def url_for(self, key: str) -> str: ...


class LocalStorage(StorageAdapter):
    def __init__(self) -> None:
        self.base = Path(settings.upload_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    async def save(self, content: bytes, ext: str) -> str:
        key = f"{uuid.uuid4().hex}.{ext}"
        (self.base / key).write_bytes(content)
        return key

    def url_for(self, key: str) -> str:
        return f"/api/files/{key}"

    def path_for(self, key: str) -> Path:
        # prevent path traversal
        p = (self.base / key).resolve()
        if not str(p).startswith(str(self.base.resolve())):
            raise ValueError("invalid key")
        return p


class S3Storage(StorageAdapter):
    """Cloudflare R2 / S3-compatible storage. Presigned GET URLs, 24h expiry."""

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        self.bucket = settings.s3_bucket

    async def save(self, content: bytes, ext: str) -> str:
        key = f"{uuid.uuid4().hex}.{ext}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return key

    def url_for(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=86400
        )


_storage: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.file_storage_mode == "s3" else LocalStorage()
    return _storage
