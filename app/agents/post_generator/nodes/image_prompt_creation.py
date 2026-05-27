"""Phase 3: Image Prompt Creation — Generate image instructions per post."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

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

    logger.info(
        "image_prompt_creation: starting",
        num_posts=len(generated_posts),
        has_human_feedback=bool(human_feedback),
    )

    # Build rich summaries — include full caption so the image LLM can extract
    # key stats, data points, and takeaways to pack into the image
    post_summaries = []
    for post in generated_posts:
        post_summaries.append({
            "post_id": post.get("post_id", ""),
            "format": post.get("format", ""),
            "trend_title": post.get("trend_title", ""),
            "caption": post.get("caption", ""),
            "hashtags": post.get("hashtags", []),
            "cta": post.get("cta", ""),
            "target_audience": post.get("target_audience", []),
        })

    system_prompt = IMAGE_PROMPT_SYSTEM_PROMPT

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
    user_content = "\n\n".join(user_content_parts)

    llm = get_content_gen_llm()

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        image_prompts = _parse_json_response(response.content)
        if not isinstance(image_prompts, list):
            image_prompts = [image_prompts]

        # Merge image prompts into posts by post_id
        prompts_by_id = {ip["post_id"]: ip for ip in image_prompts}

        updated_posts = []
        for post in generated_posts:
            post_copy = dict(post)
            img = prompts_by_id.get(post.get("post_id", ""))
            if img:
                # Remove post_id from the image prompt data (it's already on the post)
                img_data = {k: v for k, v in img.items() if k != "post_id"}
                post_copy["image_prompt"] = img_data
            else:
                post_copy["image_prompt"] = None
            updated_posts.append(post_copy)

        logger.info(
            "image_prompt_creation: completed",
            prompts_generated=len(image_prompts),
        )

        return {"generated_posts": updated_posts}

    except Exception as e:
        logger.error("image_prompt_creation: LLM call failed", error=str(e))
        # Keep posts without image prompts rather than failing
        for post in generated_posts:
            if "image_prompt" not in post:
                post["image_prompt"] = None
        return {
            "generated_posts": generated_posts,
            "errors": [{"node": "image_prompt_creation", "error": str(e)}],
        }
