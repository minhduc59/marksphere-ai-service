"""Phase 3: Image Prompt Creation — Generate image instructions per post."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.post_generator.batching import run_batches
from app.agents.post_generator.prompts import IMAGE_PROMPT_SYSTEM_PROMPT
from app.agents.post_generator.state import PostGenState
from app.clients.openai_client import get_content_gen_llm

logger = structlog.get_logger()


def _parse_json_response(content: str) -> list | dict:
    """Extract JSON from LLM response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def image_prompt_creation_node(state: PostGenState) -> dict:
    """Phase 3: Generate image prompts for all posts in a single LLM call."""
    generated_posts = state.get("generated_posts", [])
    strategy = state.get("strategy", {})
    human_feedback = (state.get("human_feedback") or "").strip()

    if not generated_posts:
        logger.warning("image_prompt_creation: no posts to process")
        return {"generated_posts": []}

    # Posts that already failed an earlier stage are skipped (no point spending
    # an LLM call on them); they pass through unchanged with image_prompt=None.
    to_process = [p for p in generated_posts if not p.get("_error")]

    logger.info(
        "image_prompt_creation: starting",
        num_posts=len(to_process),
        skipped_failed=len(generated_posts) - len(to_process),
        has_human_feedback=bool(human_feedback),
    )

    system_prompt = IMAGE_PROMPT_SYSTEM_PROMPT
    llm = get_content_gen_llm()

    async def _prompt_batch(batch: list, idx: int) -> dict:
        post_summaries = [
            {
                "post_id": post.get("post_id", ""),
                "format": post.get("format", ""),
                "trend_title": post.get("trend_title", ""),
                "caption": post.get("caption", ""),
                "hashtags": post.get("hashtags", []),
                "cta": post.get("cta", ""),
                "target_audience": post.get("target_audience", []),
            }
            for post in batch
        ]
        user_content_parts = [
            f"Generate image prompts for these {len(post_summaries)} TikTok posts:",
            json.dumps(post_summaries, indent=2),
        ]
        if human_feedback:
            # When the user rejected the previous image, surface their critique so
            # the new prompt fixes the specific issue (colors, style, composition,
            # etc.) instead of producing a similar image.
            user_content_parts.append(
                "## Human reviewer feedback on the previous image — address this directly:\n"
                f"{human_feedback}"
            )
        try:
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content="\n\n".join(user_content_parts)),
            ])
            image_prompts = _parse_json_response(response.content)
            if not isinstance(image_prompts, list):
                image_prompts = [image_prompts]
            return {"prompts": image_prompts, "error": None}
        except Exception as e:
            logger.error("image_prompt_creation: batch failed", batch=idx, error=str(e))
            return {"prompts": [], "error": {"node": "image_prompt_creation", "error": str(e)}}

    batch_results = await run_batches(to_process, _prompt_batch)

    prompts_by_id: dict = {}
    errors: list[dict] = []
    for r in batch_results:
        for ip in r["prompts"]:
            prompts_by_id[ip.get("post_id", "")] = ip
        if r["error"]:
            errors.append(r["error"])

    # Merge image prompts back into posts by post_id (preserving order). Posts
    # without a prompt (failed batch or pre-failed) keep image_prompt=None.
    updated_posts = []
    for post in generated_posts:
        post_copy = dict(post)
        img = prompts_by_id.get(post.get("post_id", ""))
        if img:
            post_copy["image_prompt"] = {k: v for k, v in img.items() if k != "post_id"}
        else:
            post_copy["image_prompt"] = None
        updated_posts.append(post_copy)

    logger.info("image_prompt_creation: completed", prompts_generated=len(prompts_by_id))

    result: dict = {"generated_posts": updated_posts}
    if errors:
        result["errors"] = errors
    return result
