import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import settings


class StorageAdapter(ABC):
    @abstractmethod
    async def save(self, content: bytes, ext: str) -> str: ...

    @abstractmethod
    def url_for(self, key: str) -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


def _content_type(key: str) -> str:
    import mimetypes

    if key.lower().endswith(".m4a"):
        return "audio/mp4"  # missing from Python's default mimetype map
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


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

    def get(self, key: str) -> bytes:
        return self.path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    def path_for(self, key: str) -> Path:
        # prevent path traversal
        p = (self.base / key).resolve()
        if not str(p).startswith(str(self.base.resolve())):
            raise ValueError("invalid key")
        return p


class S3Storage(StorageAdapter):
    """Cloudflare R2 / S3-compatible storage. Presigned GET URLs, 24h expiry.
    R2 supports the S3 API but not ACLs — no ACL parameters are ever sent."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=30),
        )
        self.bucket = settings.s3_bucket

    async def save(self, content: bytes, ext: str) -> str:
        key = f"{uuid.uuid4().hex}.{ext}"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content, ContentType=_content_type(key)
        )
        return key

    def url_for(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                # override for objects stored without ContentType so browsers render them
                "ResponseContentType": _content_type(key),
            },
            ExpiresIn=86400,
        )

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.file_storage_mode == "s3" else LocalStorage()
    return _storage
