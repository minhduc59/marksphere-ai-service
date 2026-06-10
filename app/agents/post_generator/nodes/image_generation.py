"""Phase 3.5: Image Generation — Generate images using FLUX.2-klein on Modal."""

import asyncio

import structlog

from app.agents.post_generator.state import PostGenState
from app.clients.modal_client import get_modal_client
from app.core.cloudinary_uploader import upload_image_bytes

logger = structlog.get_logger()

# Cap concurrent Modal image calls so a large batch doesn't fire hundreds of
# simultaneous requests and exhaust the model's queue / our rate budget.
IMAGE_GEN_CONCURRENCY = 6

# Map aspect_ratio strings to (width, height) matching the model's training buckets.
# TikTok is always portrait (9:16); other ratios included for completeness.
ASPECT_RATIO_SIZE_MAP: dict[str, tuple[int, int]] = {
    "1:1":  (1024, 1024),   # square bucket
    "4:5":  (896, 1152),    # portrait-ish
    "16:9": (1344, 768),    # landscape_16_9 bucket
    "9:16": (768, 1344),    # portrait bucket — TikTok native default
}


async def _generate_single_image(
    post: dict,
    scan_run_id: str,
) -> tuple[dict, dict | None]:
    """Generate image for a single post. Returns (updated_post, error_or_none)."""
    post_copy = dict(post)
    image_prompt = post.get("image_prompt")

    if not image_prompt or not image_prompt.get("prompt"):
        post_copy["image_path"] = None
        return post_copy, None

    post_id = post.get("post_id", "unknown")
    prompt_text = image_prompt["prompt"]
    aspect_ratio = image_prompt.get("aspect_ratio", "9:16")
    width, height = ASPECT_RATIO_SIZE_MAP.get(aspect_ratio, (768, 1344))

    try:
        client = get_modal_client()
        result = await client.generate_image(
            prompt=prompt_text,
            width=width,
            height=height,
        )

        public_id = f"posts/{scan_run_id}/{post_id}"
        secure_url = await upload_image_bytes(
            result.image_bytes,
            public_id=public_id,
            content_type=result.content_type,
        )

        post_copy["image_path"] = secure_url
        logger.info("image_generation: uploaded", post_id=post_id, url=secure_url)
        return post_copy, None

    except Exception as e:
        logger.error("image_generation: failed", post_id=post_id, error=repr(e))
        post_copy["image_path"] = None
        return post_copy, {
            "node": "image_generation",
            "post_id": post_id,
            "error": str(e),
        }


async def image_generation_node(state: PostGenState) -> dict:
    """Generate images for all posts concurrently using FLUX.2-klein on Modal."""
    generated_posts = state.get("generated_posts", [])
    scan_run_id = state.get("scan_run_id", "")

    if not generated_posts:
        logger.warning("image_generation: no posts to process")
        return {"generated_posts": []}

    logger.info("image_generation: starting", num_posts=len(generated_posts))

    sem = asyncio.Semaphore(IMAGE_GEN_CONCURRENCY)

    async def _bounded(post: dict) -> tuple[dict, dict | None]:
        async with sem:
            return await _generate_single_image(post, scan_run_id)

    tasks = [_bounded(post) for post in generated_posts]
    results = await asyncio.gather(*tasks)

    updated_posts = []
    errors = []
    for post, error in results:
        updated_posts.append(post)
        if error:
            errors.append(error)

    logger.info(
        "image_generation: completed",
        total=len(updated_posts),
        succeeded=len(updated_posts) - len(errors),
        failed=len(errors),
    )

    result = {"generated_posts": updated_posts}
    if errors:
        result["errors"] = errors
    return result
