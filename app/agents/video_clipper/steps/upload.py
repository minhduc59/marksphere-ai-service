"""Step 6: Upload captioned clips to Cloudinary."""
from __future__ import annotations

import structlog

from app.core.storage import get_cloudinary_storage

logger = structlog.get_logger()


def run(
    clip_local_paths: list[str],
    task_id: str,
    user_id: str,
) -> list[dict]:
    """Upload all clips to Cloudinary.

    Paths are namespaced: {user_id}/video-tasks/{task_id}/clips/clip_{i:02d}

    Returns list of {url, public_id} dicts.
    """
    storage = get_cloudinary_storage()
    results: list[dict] = []

    for i, local_path in enumerate(clip_local_paths):
        dest_key = f"{user_id}/video-tasks/{task_id}/clips/clip_{i:02d}"
        obj = storage.upload_file(local_path, dest_key, resource_type="video")
        results.append({"url": obj.url, "public_id": obj.public_id})
        logger.info(
            "upload: clip uploaded",
            index=i,
            public_id=obj.public_id,
            url=obj.url[:80],
        )

    return results
