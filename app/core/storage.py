"""Storage abstraction for report, article, media, and post files.

All storage — text reports, JSON posts, strategy files, images, and video clips —
goes through Cloudinary.  Text/JSON files use resource_type="raw"; images use
resource_type="image"; videos use resource_type="video".

Always access storage via get_storage() or get_cloudinary_storage(); do not
import cloudinary directly outside this module.
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


@dataclass
class StorageObject:
    """Result returned by upload_file — the permanent URL and the provider key."""

    url: str        # Public https URL
    public_id: str  # Provider-specific identifier (Cloudinary public_id)


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
    """Cloudinary storage backend for all file types.

    - Text/JSON files (reports, posts, strategy): resource_type="raw"
    - Images: resource_type="image"
    - Videos: resource_type="video"

    This is the ONLY place in the codebase that may import cloudinary directly.
    All new code that needs Cloudinary must go through this class via
    get_cloudinary_storage() or get_storage().
    """

    def __init__(self, settings: Settings) -> None:
        _ensure_cloudinary_configured(settings)

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def write_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        import io

        import cloudinary.uploader

        result = cloudinary.uploader.upload(
            io.BytesIO(content.encode("utf-8")),
            public_id=key,
            resource_type="raw",
            overwrite=True,
            invalidate=True,
        )
        url: str = result["secure_url"]
        logger.debug("CloudinaryStorage.write_text", public_id=key, size=len(content))
        return url

    def write_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        import io

        import cloudinary.uploader

        if content_type.startswith("video/"):
            resource_type = "video"
        elif content_type.startswith("image/"):
            resource_type = "image"
        else:
            resource_type = "raw"

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
        import cloudinary.utils
        import httpx

        url, _ = cloudinary.utils.cloudinary_url(key, resource_type="raw")
        response = httpx.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.text

    def exists(self, key: str) -> bool:
        import cloudinary.api

        for resource_type in ("raw", "image", "video"):
            try:
                cloudinary.api.resource(key, resource_type=resource_type)
                return True
            except Exception:
                pass
        return False

    def get_public_url(self, key: str) -> str:
        import cloudinary

        return cloudinary.CloudinaryImage(key).build_url(secure=True)

    def delete(self, key: str) -> bool:
        import cloudinary.uploader

        for rtype in ("raw", "image", "video"):
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
    """Return the storage backend. All environments use Cloudinary."""
    return get_cloudinary_storage(settings)
