"""Phase 4: Auto-Review Loop — Self-critique and score each post."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.post_generator.batching import run_batches
from app.agents.post_generator.prompts import AUTO_REVIEW_SYSTEM_PROMPT
from app.agents.post_generator.state import PostGenState
from app.clients.openai_client import get_review_llm

logger = structlog.get_logger()

# Criteria weights for weighted score calculation
CRITERIA_WEIGHTS = {
    "hook_strength": 0.20,
    "value_density": 0.15,
    "data_points": 0.15,
    "strategy_alignment": 0.15,
    "cta_quality": 0.10,
    "originality": 0.15,
    "format_compliance": 0.10,
}

PASSING_SCORE = 7.0
MAX_REVISIONS = 2


def _parse_json_response(content: str) -> list | dict:
    """Extract JSON from LLM response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def auto_review_node(state: PostGenState) -> dict:
    """Phase 4: Review each post against quality checklist."""
    generated_posts = state.get("generated_posts", [])
    strategy = state.get("strategy", {})
    revision_count = state.get("revision_count", 0)

    if not generated_posts:
        logger.warning("auto_review: no posts to review")
        return {
            "review_results": [],
            "revision_count": revision_count,
            "posts_to_revise": [],
        }

    # Posts that already failed generation are not reviewable; pass them through
    # with a synthetic non-revision result so they aren't sent for revision.
    to_review = [p for p in generated_posts if not p.get("_error")]
    failed_posts = [p for p in generated_posts if p.get("_error")]

    logger.info(
        "auto_review: starting",
        num_posts=len(to_review),
        skipped_failed=len(failed_posts),
        revision_round=revision_count,
    )

    brand_voice = strategy.get("brand_voice", {})
    brand_voice_block = (
        f"## Brand Voice Guidelines\n"
        f"Tone: {brand_voice.get('tone', 'professional')}\n"
        f"Personality: {brand_voice.get('personality', [])}\n"
        f"Avoid: {brand_voice.get('avoid', [])}"
    )
    llm = get_review_llm()

    async def _review_batch(batch: list, idx: int) -> dict:
        review_input = [
            {
                "post_id": post.get("post_id", ""),
                "format": post.get("format", ""),
                "caption": post.get("caption", ""),
                "hashtags": post.get("hashtags", []),
                "cta": post.get("cta", ""),
                "target_audience": post.get("target_audience", []),
                "word_count": post.get("word_count", 0),
                "trend_title": post.get("trend_title", ""),
            }
            for post in batch
        ]
        user_content = (
            f"## Posts to Review\n\n{json.dumps(review_input, indent=2)}\n\n{brand_voice_block}"
        )
        try:
            response = await llm.ainvoke([
                SystemMessage(content=AUTO_REVIEW_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ])
            reviews = _parse_json_response(response.content)
            if not isinstance(reviews, list):
                reviews = [reviews]
            return {"reviews": reviews, "error": None}
        except Exception as e:
            logger.error("auto_review: batch failed", batch=idx, error=str(e))
            # Pass this batch's posts through without revision.
            return {
                "reviews": [
                    {"post_id": p.get("post_id", ""), "weighted_score": 7.0, "needs_revision": False}
                    for p in batch
                ],
                "error": {"node": "auto_review", "error": str(e)},
            }

    batch_results = await run_batches(to_review, _review_batch)
    review_results: list[dict] = []
    errors: list[dict] = []
    for r in batch_results:
        review_results.extend(r["reviews"])
        if r["error"]:
            errors.append(r["error"])

    # Determine which posts need revision
    posts_to_revise = []
    for review in review_results:
        score = review.get("weighted_score", 0)

        # Validate/recalculate weighted score from criteria
        criteria = review.get("criteria_scores", {})
        if criteria:
            calculated = sum(
                criteria.get(k, 5) * w for k, w in CRITERIA_WEIGHTS.items()
            )
            review["weighted_score"] = round(calculated, 2)
            score = calculated

        if score < PASSING_SCORE:
            if revision_count < MAX_REVISIONS:
                review["needs_revision"] = True
                posts_to_revise.append(review["post_id"])
            else:
                # Max revisions reached — flag for human review
                review["needs_revision"] = False
                review["flagged_for_human_review"] = True
        else:
            review["needs_revision"] = False

    # Carry synthetic results for already-failed posts so review_results covers
    # every post without ever queuing a failed post for revision.
    for p in failed_posts:
        review_results.append(
            {"post_id": p.get("post_id", ""), "weighted_score": 0.0, "needs_revision": False}
        )

    logger.info(
        "auto_review: completed",
        passing=len(to_review) - len(posts_to_revise),
        needs_revision=len(posts_to_revise),
        revision_round=revision_count,
    )

    result: dict = {
        "review_results": review_results,
        "revision_count": revision_count + 1,
        "posts_to_revise": posts_to_revise,
    }
    if errors:
        result["errors"] = errors
    return result
