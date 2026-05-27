"""Phase 3.5: Image Generation — Generate images using OpenAI gpt-image-1.5."""

import asyncio

import structlog

from app.agents.post_generator.state import PostGenState
from app.clients.bfl_client import get_image_client
from app.core.cloudinary_uploader import upload_image_bytes

logger = structlog.get_logger()

# Map aspect_ratio strings to OpenAI size strings
ASPECT_RATIO_SIZE_MAP: dict[str, str] = {
    "1:1": "1024x1024",
    "4:5": "1024x1536",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
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
    aspect_ratio = image_prompt.get("aspect_ratio", "1:1")
    size = ASPECT_RATIO_SIZE_MAP.get(aspect_ratio, "1024x1024")

    try:
        client = get_image_client()
        result = await client.generate_image(
            prompt=prompt_text,
            size=size,
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
    """Generate images for all posts concurrently using OpenAI gpt-image-1.5."""
    generated_posts = state.get("generated_posts", [])
    scan_run_id = state.get("scan_run_id", "")

    if not generated_posts:
        logger.warning("image_generation: no posts to process")
        return {"generated_posts": []}

    logger.info("image_generation: starting", num_posts=len(generated_posts))

    tasks = [
        _generate_single_image(post, scan_run_id)
        for post in generated_posts
    ]
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
