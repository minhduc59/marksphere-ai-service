"""Phase 5: Output Packaging — Structure final output, save to storage and DB."""

import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.agents.post_generator.state import PostGenState
from app.core.storage import get_storage
from app.db.models import ContentPost, ContentStatus, PostFormat, ScanRun
from app.db.session import async_session_factory

logger = structlog.get_logger()

FORMAT_MAP = {
    "quick_tips": PostFormat.QUICK_TIPS,
    "hot_take": PostFormat.HOT_TAKE,
    "trending_breakdown": PostFormat.TRENDING_BREAKDOWN,
    "did_you_know": PostFormat.DID_YOU_KNOW,
    "tutorial_hack": PostFormat.TUTORIAL_HACK,
    "myth_busters": PostFormat.MYTH_BUSTERS,
    "behind_the_tech": PostFormat.BEHIND_THE_TECH,
}


def _build_strategy_update(
    state: PostGenState,
    posts: list[dict],
    review_results: list[dict],
) -> dict:
    """Build the strategy_update section for the output."""
    strategy = state.get("strategy", {})
    content_plan = state.get("content_plan", [])

    trends_used = list({p.get("trend_title", "") for p in posts})
    formats_used = {}
    for p in posts:
        fmt = p.get("format", "unknown")
        formats_used[fmt] = formats_used.get(fmt, 0) + 1

    audiences = set()
    for p in posts:
        for a in p.get("target_audience", []):
            audiences.add(a)

    scores = [r.get("weighted_score", 0) for r in review_results if r.get("weighted_score")]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    diversity = "high" if len(formats_used) >= 3 else "medium" if len(formats_used) >= 2 else "low"

    return {
        "version": str(float(strategy.get("version", "1.0")) + 0.1),
        "trends_leveraged": trends_used,
        "formats_distribution": formats_used,
        "audience_focus": list(audiences),
        "performance_baseline": {
            "avg_review_score": avg_score,
            "content_diversity_score": diversity,
        },
        "notes_for_feedback_agent": (
            f"Monitor engagement on {len(posts)} posts covering: {', '.join(trends_used[:3])}. "
            f"Format mix: {formats_used}."
        ),
    }


def _build_final_output(state: PostGenState) -> dict:
    """Assemble the final output JSON."""
    posts = state.get("generated_posts", [])
    review_results = state.get("review_results", [])
    content_plan = state.get("content_plan", [])
    strategy = state.get("strategy", {})

    review_by_id = {r["post_id"]: r for r in review_results}

    # Enrich posts with review data and metadata
    final_posts = []
    for post in posts:
        post_id = post.get("post_id", "")
        review = review_by_id.get(post_id, {})

        posting_insights = strategy.get("posting_insights", {})

        final_post = {
            "post_id": post_id,
            "status": (
                "flagged_for_review"
                if review.get("flagged_for_human_review")
                else "draft"
            ),
            "trend_source": {
                "trend_name": post.get("trend_title", ""),
                "trend_url": post.get("trend_url", ""),
                "content_angle_used": post.get("content_angle_used", ""),
            },
            "format": post.get("format", ""),
            "target_audience": post.get("target_audience", []),
            "caption": post.get("caption", ""),
            "hashtags": post.get("hashtags", []),
            "cta": post.get("cta", ""),
            "image_prompt": post.get("image_prompt"),
            "image_path": post.get("image_path"),
            "is_promoted": post.get("is_promoted", False),
            "metadata": {
                "word_count": post.get("word_count", 0),
                "estimated_read_time": post.get("estimated_read_time", ""),
                "engagement_prediction": post.get("engagement_prediction", "medium"),
                "best_posting_day": posting_insights.get("best_days", ["Tuesday"])[0],
                "best_posting_time": posting_insights.get("best_times", ["8:00-10:00 AM"])[0],
                "timing_window": post.get("timing_window", ""),
            },
            "review": {
                "score": review.get("weighted_score", 0),
                "notes": review.get("feedback", ""),
                "criteria": review.get("criteria_scores", {}),
                "revision_count": state.get("revision_count", 0),
            },
        }
        final_posts.append(final_post)

    strategy_update = _build_strategy_update(state, posts, review_results)

    return {
        "content_plan": {
            "total_posts": len(final_posts),
            "strategy_version": strategy.get("version", "1.0"),
            "trends_used": list({p["trend_source"]["trend_name"] for p in final_posts}),
            "formats_used": list({p["format"] for p in final_posts}),
        },
        "posts": final_posts,
        "strategy_update": strategy_update,
    }


async def _save_to_storage(scan_run_id: str, final_output: dict) -> list[str]:
    """Save posts and output to storage backend."""
    storage = get_storage()
    saved_paths = []

    # Save complete output
    output_key = f"posts/{scan_run_id}/output.json"
    path = storage.write_text(
        output_key,
        json.dumps(final_output, indent=2, ensure_ascii=False),
        "application/json",
    )
    saved_paths.append(path)

    # Save individual post files
    for post in final_output.get("posts", []):
        post_id = post.get("post_id", "unknown")
        post_key = f"posts/{scan_run_id}/{post_id}.json"
        path = storage.write_text(
            post_key,
            json.dumps(post, indent=2, ensure_ascii=False),
            "application/json",
        )
        saved_paths.append(path)

    return saved_paths


async def _persist_to_db(
    scan_run_id: str, final_output: dict, user_id: str | None = None
) -> None:
    """Save posts to the content_posts database table."""
    async with async_session_factory() as db:
        try:
            # Verify scan run exists
            result = await db.execute(
                select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
            )
            scan_run = result.scalar_one_or_none()
            if not scan_run:
                logger.error("output_packaging: scan_run not found", scan_run_id=scan_run_id)
                return

            for post in final_output.get("posts", []):
                fmt_str = post.get("format", "quick_tips")
                fmt = FORMAT_MAP.get(fmt_str, PostFormat.QUICK_TIPS)

                status = (
                    ContentStatus.FLAGGED_FOR_REVIEW
                    if post.get("status") == "flagged_for_review"
                    else ContentStatus.DRAFT
                )

                review = post.get("review", {})
                metadata = post.get("metadata", {})

                content_post = ContentPost(
                    scan_run_id=uuid.UUID(scan_run_id),
                    created_by=uuid.UUID(user_id) if user_id else None,
                    format=fmt,
                    caption=post.get("caption", ""),
                    hashtags=post.get("hashtags", []),
                    cta=post.get("cta"),
                    image_prompt=post.get("image_prompt"),
                    trend_title=post.get("trend_source", {}).get("trend_name", "")[:500],
                    trend_url=post.get("trend_source", {}).get("trend_url"),
                    content_angle_used=post.get("trend_source", {}).get("content_angle_used"),
                    target_audience=post.get("target_audience", []),
                    word_count=metadata.get("word_count"),
                    estimated_read_time=metadata.get("estimated_read_time"),
                    engagement_prediction=metadata.get("engagement_prediction"),
                    best_posting_day=metadata.get("best_posting_day"),
                    best_posting_time=metadata.get("best_posting_time"),
                    timing_window=metadata.get("timing_window"),
                    status=status,
                    review_score=review.get("score"),
                    review_notes=review.get("notes"),
                    review_criteria=review.get("criteria"),
                    revision_count=review.get("revision_count", 0),
                    is_promoted=post.get("is_promoted", False),
                    file_path=f"posts/{scan_run_id}/{post.get('post_id', 'unknown')}.json",
                    image_path=post.get("image_path"),
                )
                db.add(content_post)

            await db.commit()
            logger.info(
                "output_packaging: persisted to DB",
                scan_run_id=scan_run_id,
                posts_saved=len(final_output.get("posts", [])),
            )

        except Exception as e:
            await db.rollback()
            logger.error("output_packaging: DB persist failed", error=str(e))
            raise


async def output_packaging_node(state: PostGenState) -> dict:
    """Phase 5: Package final output, save to storage and DB."""
    scan_run_id = state["scan_run_id"]

    logger.info("output_packaging: starting", scan_run_id=scan_run_id)

    # Build final output
    final_output = _build_final_output(state)

    # Save to storage
    try:
        saved_paths = await _save_to_storage(scan_run_id, final_output)
    except Exception as e:
        logger.error("output_packaging: storage save failed", error=str(e))
        saved_paths = []

    # Persist to DB
    try:
        await _persist_to_db(scan_run_id, final_output, state.get("user_id"))
    except Exception as e:
        logger.error("output_packaging: DB persist failed", error=str(e))

    # Save strategy update
    try:
        storage = get_storage()
        strategy_update = final_output.get("strategy_update", {})
        strategy_key = f"strategy/{scan_run_id}/strategy_update.json"
        storage.write_text(
            strategy_key,
            json.dumps(strategy_update, indent=2, ensure_ascii=False),
            "application/json",
        )
    except Exception as e:
        logger.warning("output_packaging: strategy update save failed", error=str(e))

    total_posts = len(final_output.get("posts", []))
    flagged = sum(
        1 for p in final_output.get("posts", [])
        if p.get("status") == "flagged_for_review"
    )

    logger.info(
        "output_packaging: completed",
        total_posts=total_posts,
        flagged_for_review=flagged,
        files_saved=len(saved_paths),
    )

    return {
        "final_output": final_output,
        "saved_file_paths": saved_paths,
    }
