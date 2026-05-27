"""Phase 2: Content Generation — Generate TikTok posts from content plan."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.post_generator.prompts import (
    CONTENT_GENERATION_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
)
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


def _build_brand_voice_instructions(strategy: dict) -> str:
    """Build brand voice instructions from strategy."""
    voice = strategy.get("brand_voice", {})
    prefs = strategy.get("content_preferences", {})

    lines = []
    if voice.get("tone"):
        lines.append(f"Tone: {voice['tone']}")
    if voice.get("personality"):
        lines.append(f"Personality: {', '.join(voice['personality'])}")
    if voice.get("avoid"):
        lines.append(f"Avoid: {', '.join(voice['avoid'])}")
    if voice.get("tiktok_persona"):
        lines.append(f"Persona: {voice['tiktok_persona']}")
    if prefs.get("max_emojis"):
        lines.append(f"Max emojis per post: {prefs['max_emojis']}")
    if prefs.get("cta_style"):
        lines.append(f"Preferred CTA style: {prefs['cta_style']}")

    return "\n".join(lines) if lines else "Energetic, casual, data-driven tech creator tone."


def _build_generation_input(
    content_plan: list[dict],
    analyzed_trends: list[dict],
    strategy: dict,
) -> str:
    """Build user message for content generation."""
    posts_input = []
    for plan_item in content_plan:
        trend_idx = plan_item.get("trend_index", 0)
        trend = (
            analyzed_trends[trend_idx]
            if trend_idx < len(analyzed_trends)
            else analyzed_trends[0] if analyzed_trends else {}
        )

        posts_input.append({
            "plan": plan_item,
            "trend_data": {
                "title": trend.get("title", ""),
                "source_url": trend.get("source_url", ""),
                "cleaned_content": (trend.get("cleaned_content") or "")[:3000],
                "key_data_points": trend.get("key_data_points", []),
                "content_angles": trend.get("content_angles", []),
                "target_audience": trend.get("target_audience", []),
                "sentiment": trend.get("sentiment"),
                "lifecycle": trend.get("lifecycle"),
                "engagement_prediction": trend.get("engagement_prediction"),
                "likes": trend.get("likes"),
                "comments_count": trend.get("comments_count"),
            },
        })

    posting = strategy.get("posting_insights", {})
    return (
        f"## Posts to Generate\n\n{json.dumps(posts_input, indent=2, default=str)}\n\n"
        f"## Posting Schedule\n"
        f"Best days: {posting.get('best_days', [])}\n"
        f"Best times: {posting.get('best_times', [])}\n"
        f"Timezone: {posting.get('timezone', 'UTC')}"
    )


def _build_revision_input(
    posts_to_revise: list[str],
    generated_posts: list[dict],
    review_results: list[dict],
    analyzed_trends: list[dict],
    human_feedback: str | None = None,
) -> str:
    """Build user message for revision pass.

    If ``human_feedback`` is provided, it is attached to every post being revised
    and the prompt asks the model to treat it as the primary signal (the system
    prompt already explains the precedence).
    """
    revision_items = []
    review_by_id = {r["post_id"]: r for r in review_results}
    human_feedback_text = (human_feedback or "").strip()

    for post in generated_posts:
        if post["post_id"] in posts_to_revise:
            review = review_by_id.get(post["post_id"], {})
            # Find the matching trend data
            trend_title = post.get("trend_title", "")
            trend_data = next(
                (t for t in analyzed_trends if t.get("title") == trend_title),
                {},
            )
            item: dict = {
                "original_post": post,
                "review_feedback": review.get("feedback", ""),
                "criteria_scores": review.get("criteria_scores", {}),
                "trend_data": {
                    "title": trend_data.get("title", ""),
                    "key_data_points": trend_data.get("key_data_points", []),
                    "content_angles": trend_data.get("content_angles", []),
                    "cleaned_content": (trend_data.get("cleaned_content") or "")[:2000],
                },
            }
            if human_feedback_text:
                item["human_feedback"] = human_feedback_text
            revision_items.append(item)

    return json.dumps(revision_items, indent=2, default=str)


async def content_generation_node(state: PostGenState) -> dict:
    """Phase 2: Generate TikTok posts (or revise failing ones)."""
    posts_to_revise = state.get("posts_to_revise", [])
    content_plan = state.get("content_plan", [])
    analyzed_trends = state.get("analyzed_trends", [])
    strategy = state.get("strategy", {})
    existing_posts = state.get("generated_posts", [])

    is_revision = bool(posts_to_revise)

    logger.info(
        "content_generation: starting",
        is_revision=is_revision,
        posts_to_revise=len(posts_to_revise) if is_revision else 0,
        content_plan_size=len(content_plan),
    )

    if not content_plan and not is_revision:
        logger.warning("content_generation: no content plan")
        return {"generated_posts": []}

    llm = get_content_gen_llm()

    try:
        if is_revision:
            # Revision mode: only regenerate failing posts. ``human_feedback``
            # (if present) overrides the auto-review feedback per the system
            # prompt rules.
            review_results = state.get("review_results", [])
            human_feedback = state.get("human_feedback")
            user_content = _build_revision_input(
                posts_to_revise,
                existing_posts,
                review_results,
                analyzed_trends,
                human_feedback=human_feedback,
            )
            messages = [
                SystemMessage(content=REVISION_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ]
        else:
            # First run: generate all posts
            brand_voice = _build_brand_voice_instructions(strategy)
            system_prompt = CONTENT_GENERATION_SYSTEM_PROMPT.format(
                brand_voice_instructions=brand_voice
            )
            user_content = _build_generation_input(content_plan, analyzed_trends, strategy)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]

        response = await llm.ainvoke(messages)
        new_posts = _parse_json_response(response.content)

        if not isinstance(new_posts, list):
            new_posts = [new_posts]

        if not is_revision and len(new_posts) != len(content_plan):
            logger.warning(
                "content_generation: post count mismatch with content plan",
                content_plan_size=len(content_plan),
                generated_count=len(new_posts),
            )

        # Propagate is_promoted flag from analyzed_trends to generated posts
        if not is_revision:
            trend_promoted = {
                t.get("title", ""): t.get("is_promoted", False)
                for t in analyzed_trends
            }
            for post in new_posts:
                post["is_promoted"] = trend_promoted.get(
                    post.get("trend_title", ""), False
                )

        if is_revision:
            # Merge revised posts back: replace old versions, keep passing ones
            revised_ids = {p["post_id"] for p in new_posts}
            merged = [p for p in existing_posts if p["post_id"] not in revised_ids]
            merged.extend(new_posts)
            result_posts = merged
        else:
            result_posts = new_posts

        logger.info(
            "content_generation: completed",
            total_posts=len(result_posts),
            revised=len(new_posts) if is_revision else 0,
        )

        return {"generated_posts": result_posts}

    except Exception as e:
        logger.error("content_generation: LLM call failed", error=str(e))
        return {
            "generated_posts": existing_posts,
            "errors": [{"node": "content_generation", "error": str(e)}],
        }
