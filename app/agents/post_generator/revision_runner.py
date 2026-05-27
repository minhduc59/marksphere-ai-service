"""Human-feedback-driven regeneration runner for a single ContentPost.

When a user rejects a generated post via ``POST /v1/posts/{id}/review``,
the backend forwards the feedback to ``POST /api/v1/posts/{id}/regenerate``
which spawns this runner as a background task.

Flow:
  1. Lock and load the ContentPost row, ensure status is needs_revision.
  2. Flip status to REGENERATING and commit so polling sees the transition.
  3. Use the LLM-driven feedback_classifier to decide whether to regenerate
     the caption/hashtags/CTA, the image, or both.
  4. Run only the necessary post-generator nodes directly (skip the full
     LangGraph — strategy/plan stages are already baked into the existing
     row).
  5. Overwrite the same row with the new content, bump revision_count, and
     set status back to DRAFT. On any unhandled error, set the status to
     FLAGGED_FOR_REVIEW and store the error in review_notes.
"""

import time
import uuid

import structlog
from sqlalchemy import select

from app.agents.post_generator.nodes.content_generation import content_generation_node
from app.agents.post_generator.nodes.feedback_classifier import classify_feedback
from app.agents.post_generator.nodes.image_generation import image_generation_node
from app.agents.post_generator.nodes.image_prompt_creation import (
    image_prompt_creation_node,
)
from app.agents.post_generator.state import PostGenState
from app.db.models import ContentPost, ContentStatus
from app.db.session import async_session_factory

logger = structlog.get_logger()


# LangGraph-internal post identifier used while the pipeline shuttles posts
# through state. The DB row UUID is the durable identifier.
_INTERNAL_POST_ID = "post-001"


def _post_to_state_dict(post: ContentPost) -> dict:
    """Project a ContentPost row into the dict shape the generator nodes expect."""
    return {
        "post_id": _INTERNAL_POST_ID,
        "trend_title": post.trend_title or "",
        "trend_url": post.trend_url,
        "format": post.format.value if post.format else "quick_tips",
        "caption": post.caption or "",
        "hashtags": list(post.hashtags or []),
        "cta": post.cta or "",
        "image_prompt": post.image_prompt,
        "target_audience": list(post.target_audience or []),
        "word_count": post.word_count,
        "content_angle_used": post.content_angle_used,
        "is_promoted": bool(post.is_promoted),
    }


async def _set_status(
    post_id: uuid.UUID,
    new_status: ContentStatus,
    *,
    review_notes: str | None = None,
) -> None:
    """Update only the status (and optionally review_notes) on its own transaction."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(ContentPost).where(ContentPost.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post:
            return
        post.status = new_status
        if review_notes is not None:
            post.review_notes = review_notes
        await db.commit()


async def run_human_feedback_revision(
    post_id: str,
    feedback: str,
    request_id: str | None = None,
) -> None:
    """Regenerate a single ContentPost row based on free-form user feedback.

    Args:
        post_id: UUID (string) of the ContentPost row to regenerate.
        feedback: Free-form rejection feedback from the user.
        request_id: Optional request ID for log correlation.
    """
    start = time.time()
    post_uuid = uuid.UUID(post_id)
    log = logger.bind(post_id=post_id, request_id=request_id)

    # --- Step 1+2: load and flip status to REGENERATING ----------------------
    async with async_session_factory() as db:
        result = await db.execute(
            select(ContentPost)
            .where(ContentPost.id == post_uuid)
            .with_for_update()
        )
        post = result.scalar_one_or_none()
        if not post:
            log.error("revision_runner: post not found")
            return

        # Only regenerate posts that the review endpoint flagged. If the user
        # double-clicks or the task is retried, this guards against duplicate
        # regenerations.
        if post.status != ContentStatus.NEEDS_REVISION:
            log.warning(
                "revision_runner: post not in needs_revision; skipping",
                status=post.status.value,
            )
            return

        post.status = ContentStatus.REGENERATING
        post.human_feedback = feedback
        await db.commit()
        await db.refresh(post)
        post_snapshot = _post_to_state_dict(post)
        scan_run_id = str(post.scan_run_id)
        current_revision_count = post.revision_count or 0

    log.info("revision_runner: regenerating", scan_run_id=scan_run_id)

    # --- Step 3: classify feedback ------------------------------------------
    try:
        targets = await classify_feedback(feedback, post_snapshot)
    except Exception as exc:  # noqa: BLE001 — classifier has its own fallback, this catches anything else
        log.error("revision_runner: classifier crashed", error=str(exc))
        await _set_status(
            post_uuid,
            ContentStatus.FLAGGED_FOR_REVIEW,
            review_notes=f"Feedback classifier failed: {exc}",
        )
        return

    regen_content = bool(targets.get("regenerate_content"))
    regen_image = bool(targets.get("regenerate_image"))

    # --- Step 4: run only the targeted nodes --------------------------------
    state: PostGenState = {  # type: ignore[typeddict-item]  # partial state is fine for these nodes
        "scan_run_id": scan_run_id,
        "user_id": None,
        "options": {},
        "trend_report_md": "",
        "analyzed_trends": [],
        "strategy": {},
        "content_plan": [],
        "generated_posts": [post_snapshot],
        "review_results": [],
        "revision_count": current_revision_count + 1,
        "posts_to_revise": [_INTERNAL_POST_ID] if regen_content else [],
        "human_feedback": feedback,
        "revision_targets": {"content": regen_content, "image": regen_image},
        "final_output": {},
        "saved_file_paths": [],
        "errors": [],
    }

    try:
        if regen_content:
            update = await content_generation_node(state)
            posts = update.get("generated_posts") or []
            if not posts:
                raise RuntimeError("content_generation produced no posts")
            # The revision branch returns the merged list; we only have one post.
            state["generated_posts"] = posts

        if regen_image:
            # image_generation uses the post's post_id as part of the
            # cloudinary key. Use the DB UUID so each regeneration overwrites
            # the row's image at a stable URL slot, suffixed with the new
            # revision_count so old CDN caches don't serve stale bytes.
            new_post_id = f"{post_uuid}-r{current_revision_count + 1}"
            for p in state["generated_posts"]:
                p["post_id"] = new_post_id

            prompt_update = await image_prompt_creation_node(state)
            state["generated_posts"] = prompt_update.get(
                "generated_posts", state["generated_posts"]
            )

            image_update = await image_generation_node(state)
            state["generated_posts"] = image_update.get(
                "generated_posts", state["generated_posts"]
            )
    except Exception as exc:  # noqa: BLE001 — surface any node failure to the user
        log.error("revision_runner: node failure", error=str(exc))
        await _set_status(
            post_uuid,
            ContentStatus.FLAGGED_FOR_REVIEW,
            review_notes=f"Regeneration failed: {exc}",
        )
        return

    new_post = state["generated_posts"][0]

    # --- Step 5: persist the new content, revert status to DRAFT -------------
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(ContentPost)
                .where(ContentPost.id == post_uuid)
                .with_for_update()
            )
            row = result.scalar_one_or_none()
            if not row:
                log.error("revision_runner: row vanished before persist")
                return

            if regen_content:
                row.caption = new_post.get("caption") or row.caption
                row.hashtags = new_post.get("hashtags") or row.hashtags
                row.cta = new_post.get("cta") or row.cta
                wc = new_post.get("word_count")
                if isinstance(wc, int):
                    row.word_count = wc

            if regen_image:
                row.image_prompt = new_post.get("image_prompt") or row.image_prompt
                new_image_path = new_post.get("image_path")
                if new_image_path:
                    row.image_path = new_image_path

            row.revision_count = current_revision_count + 1
            row.last_revision_targets = {
                "content": regen_content,
                "image": regen_image,
                "reasoning": targets.get("reasoning", ""),
            }
            row.status = ContentStatus.DRAFT
            # Clear stale auto-review feedback so the UI shows a fresh slate.
            row.review_notes = None

            await db.commit()
    except Exception as exc:  # noqa: BLE001 — persistence failures must surface as flagged
        log.error("revision_runner: persist failed", error=str(exc))
        await _set_status(
            post_uuid,
            ContentStatus.FLAGGED_FOR_REVIEW,
            review_notes=f"Regeneration persisted partial state: {exc}",
        )
        return

    duration_ms = int((time.time() - start) * 1000)
    log.info(
        "revision_runner: completed",
        duration_ms=duration_ms,
        regen_content=regen_content,
        regen_image=regen_image,
        revision_count=current_revision_count + 1,
    )
