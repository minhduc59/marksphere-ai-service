"""Storage abstraction for report, article, and media files.

- Development: writes to local filesystem under ai-service/
  Public URLs served via FastAPI StaticFiles mount (+ ngrok for TikTok API).
- Production: uploads to S3 bucket, public URLs via presigned URLs or CloudFront.
- Cloudinary: used for generated images and video clips. Call get_cloudinary_storage()
  to get a CloudinaryStorage instance; do not import the cloudinary SDK anywhere else.
"""

from __future__ import annotations

import abc
import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.config import Settings, get_settings

logger = structlog.get_logger()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # ai-service/


@dataclass
class StorageObject:
    """Result returned by upload_file — the permanent URL and the provider key."""

    url: str        # Public https URL
    public_id: str  # Provider-specific identifier (Cloudinary public_id, S3 key, local path)


class StorageBackend(abc.ABC):
    """Abstract storage interface."""

    @abc.abstractmethod
    def write_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        """Write text content. Returns the storage path/URL."""

    @abc.abstractmethod
    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Write binary content (e.g. images). Returns the storage path/URL."""

    @abc.abstractmethod
    def read_text(self, key: str) -> str:
        """Read text content by key."""

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""

    @abc.abstractmethod
    def get_public_url(self, key: str) -> str:
        """Get a publicly accessible URL for the given storage key.

        Used by TikTok's PULL_FROM_URL to download media files.
        Dev: ngrok-tunneled static file URL. Prod: S3 presigned URL.
        """

    @abc.abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a file by storage key. Returns True if deleted."""

    def upload_file(
        self,
        local_path: str,
        dest_key: str,
        resource_type: str = "auto",
    ) -> StorageObject:
        """Upload a file from a local path and return its URL + key.

        Default implementation reads bytes and delegates to write_bytes.
        CloudinaryStorage overrides this to call the SDK directly (avoids
        loading the whole file into memory for large video files).
        """
        data = Path(local_path).read_bytes()
        url = self.write_bytes(dest_key, data)
        return StorageObject(url=url, public_id=dest_key)

    def download_file(self, source_key: str, local_path: str) -> None:
        """Download a stored file to a local path.

        Default implementation is not supported — subclasses override as needed.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support download_file"
        )


class LocalStorage(StorageBackend):
    """Local filesystem storage under ai-service/."""

    def __init__(self, base_dir: Path = BASE_DIR) -> None:
        self.base_dir = base_dir

    def write_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.debug("LocalStorage: written", path=str(path))
        return key

    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug("LocalStorage: written bytes", path=str(path), size=len(data))
        return key

    def read_text(self, key: str) -> str:
        path = self.base_dir / key
        return path.read_text(encoding="utf-8")

    def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()

    def get_public_url(self, key: str) -> str:
        settings = get_settings()
        return f"{settings.STORAGE_PUBLIC_BASE_URL}/{key}"

    def delete(self, key: str) -> bool:
        path = self.base_dir / key
        if path.exists():
            path.unlink()
            logger.debug("LocalStorage: deleted", path=str(path))
            return True
        return False


class S3Storage(StorageBackend):
    """AWS S3 storage backend."""

    def __init__(self, bucket: str, region: str, prefix: str) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self.client = boto3.client("s3", region_name=region)

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def write_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        full_key = self._full_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )
        s3_path = f"s3://{self.bucket}/{full_key}"
        logger.debug("S3Storage: uploaded", s3_path=s3_path)
        return s3_path

    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        full_key = self._full_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=data,
            ContentType=content_type,
        )
        s3_path = f"s3://{self.bucket}/{full_key}"
        logger.debug("S3Storage: uploaded bytes", s3_path=s3_path, size=len(data))
        return s3_path

    def read_text(self, key: str) -> str:
        full_key = self._full_key(key)
        response = self.client.get_object(Bucket=self.bucket, Key=full_key)
        return response["Body"].read().decode("utf-8")

    def exists(self, key: str) -> bool:
        import botocore.exceptions

        full_key = self._full_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=full_key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def get_public_url(self, key: str) -> str:
        full_key = self._full_key(key)
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": full_key},
            ExpiresIn=3600,
        )

    def delete(self, key: str) -> bool:
        full_key = self._full_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=full_key)
        logger.debug("S3Storage: deleted", key=full_key)
        return True


_CLOUDINARY_CONFIG_LOCK = threading.Lock()
_CLOUDINARY_CONFIGURED = False


def _ensure_cloudinary_configured(settings: Settings) -> None:
    global _CLOUDINARY_CONFIGURED
    if _CLOUDINARY_CONFIGURED:
        return
    with _CLOUDINARY_CONFIG_LOCK:
        if _CLOUDINARY_CONFIGURED:
            return
        import cloudinary

        missing = [
            name
            for name, val in (
                ("CLOUDINARY_CLOUD_NAME", settings.CLOUDINARY_CLOUD_NAME),
                ("CLOUDINARY_API_KEY", settings.CLOUDINARY_API_KEY),
                ("CLOUDINARY_API_SECRET", settings.CLOUDINARY_API_SECRET),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "CloudinaryStorage: missing env vars: " + ", ".join(missing)
            )
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        _CLOUDINARY_CONFIGURED = True


class CloudinaryStorage(StorageBackend):
    """Cloudinary storage backend for media files (images, videos, fonts).

    This is the ONLY place in the codebase that may import cloudinary directly.
    All new code that needs Cloudinary must go through this class via
    get_cloudinary_storage().  The legacy cloudinary_uploader module is kept
    for the existing photo pipeline; do not add new usages there.

    Paths are namespaced by the caller: {user_id}/video-tasks/{task_id}/...
    """

    def __init__(self, settings: Settings) -> None:
        _ensure_cloudinary_configured(settings)

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def write_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        raise NotImplementedError("CloudinaryStorage does not support text files")

    def write_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        import cloudinary.uploader
        import io

        resource_type = "video" if content_type.startswith("video/") else "image"
        result = cloudinary.uploader.upload(
            io.BytesIO(data),
            public_id=key,
            resource_type=resource_type,
            overwrite=True,
            invalidate=True,
        )
        url: str = result["secure_url"]
        logger.debug("CloudinaryStorage.write_bytes", public_id=key, bytes=len(data))
        return url

    def read_text(self, key: str) -> str:
        raise NotImplementedError("CloudinaryStorage does not support text reads")

    def exists(self, key: str) -> bool:
        import cloudinary.api

        try:
            cloudinary.api.resource(key)
            return True
        except Exception:
            return False

    def get_public_url(self, key: str) -> str:
        import cloudinary

        return cloudinary.CloudinaryImage(key).build_url(secure=True)

    def delete(self, key: str) -> bool:
        import cloudinary.uploader

        # Try both resource types; Cloudinary returns ok/not found regardless
        for rtype in ("image", "video", "raw"):
            result = cloudinary.uploader.destroy(key, resource_type=rtype)
            if result.get("result") == "ok":
                logger.debug("CloudinaryStorage.delete", public_id=key, resource_type=rtype)
                return True
        return False

    # ------------------------------------------------------------------
    # Extended interface (video-clipper specific)
    # ------------------------------------------------------------------

    def upload_file(
        self,
        local_path: str,
        dest_key: str,
        resource_type: str = "auto",
    ) -> StorageObject:
        """Upload a local file to Cloudinary without loading it fully into memory."""
        import cloudinary.uploader

        result = cloudinary.uploader.upload(
            local_path,
            public_id=dest_key,
            resource_type=resource_type,
            overwrite=True,
            invalidate=True,
        )
        obj = StorageObject(url=result["secure_url"], public_id=result["public_id"])
        logger.info(
            "CloudinaryStorage.upload_file",
            local_path=local_path,
            public_id=obj.public_id,
            url=obj.url[:80],
        )
        return obj

    async def upload_file_async(
        self,
        local_path: str,
        dest_key: str,
        resource_type: str = "auto",
    ) -> StorageObject:
        """Non-blocking upload — wraps upload_file in a thread-pool executor."""
        return await asyncio.to_thread(self.upload_file, local_path, dest_key, resource_type)

    def download_file(self, source_key: str, local_path: str) -> None:
        """Download a Cloudinary asset to a local path (used for source video + fonts)."""
        import urllib.request
        import cloudinary

        url = cloudinary.CloudinaryImage(source_key).build_url(secure=True)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, local_path)  # noqa: S310 — trusted Cloudinary URL
        logger.debug("CloudinaryStorage.download_file", public_id=source_key, dest=local_path)

    async def download_file_async(self, source_key: str, local_path: str) -> None:
        """Non-blocking download."""
        await asyncio.to_thread(self.download_file, source_key, local_path)


def get_cloudinary_storage(settings: Settings | None = None) -> CloudinaryStorage:
    """Return a CloudinaryStorage instance.

    Raises RuntimeError if Cloudinary credentials are not set in the environment.
    """
    if settings is None:
        settings = get_settings()
    return CloudinaryStorage(settings)


def get_storage(settings: Settings | None = None) -> StorageBackend:
    """Return the appropriate storage backend based on APP_ENV."""
    if settings is None:
        settings = get_settings()

    if settings.is_production and settings.S3_BUCKET:
        logger.info(
            "Using S3 storage",
            bucket=settings.S3_BUCKET,
            prefix=settings.S3_PREFIX,
        )
        return S3Storage(
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
            prefix=settings.S3_PREFIX,
        )

    logger.info("Using local filesystem storage", base_dir=str(BASE_DIR))
    return LocalStorage(BASE_DIR)
