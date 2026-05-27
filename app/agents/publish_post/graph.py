"""LangGraph graph definition for the Publish Post Agent.

Graph flow:
    START → resolve_and_validate → golden_hour → scheduler → publish_node → END

The publisher (Zernio, via NestJS backend) handles scheduled delivery — when
`scheduled_at` is set, publish_node forwards `scheduledFor` and the publisher
publishes at the chosen time.
"""

from __future__ import annotations

import uuid

import httpx
import structlog
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents.publish_post.caption_assembler import assemble_caption
from app.agents.publish_post.failure_handler import mark_publish_failed
from app.agents.publish_post.golden_hour import golden_hour_node
from app.agents.publish_post.publish_node import publish_node
from app.agents.publish_post.scheduler_node import scheduler_node
from app.agents.publish_post.state import PublishPostState
from app.config import get_settings
from app.core.cloudinary_uploader import assert_cloudinary_url
from app.db.models.content_post import ContentPost
from app.db.models.enums import ContentStatus, PublishMode, PublishStatus
from app.db.models.published_post import PublishedPost
from app.db.session import async_session_factory

logger = structlog.get_logger()


async def resolve_and_validate_node(state: PublishPostState) -> dict:
    """Resolve all data needed for publishing:

    1. Load ContentPost from DB, validate status = approved
    2. Check for duplicate published record
    3. Create PublishedPost record (status = PROCESSING)
    4. Resolve image public URL via StorageBackend
    5. Assemble caption (caption + hashtags + CTA)

    NOTE: TikTok account / publisher validation is handled by the NestJS
    backend in the internal publish endpoint. We no longer need to check
    OAuth tokens here.
    """
    try:
        return await _resolve_and_validate_impl(state)
    except Exception as exc:
        preexisting_id = state.get("published_post_id") or ""
        if preexisting_id:
            await mark_publish_failed(
                published_post_id=preexisting_id,
                error_message=str(exc),
                stage="resolve",
            )
        raise


async def _resolve_and_validate_impl(state: PublishPostState) -> dict:
    content_post_id = state["content_post_id"]
    publish_mode = state.get("publish_mode", "auto")
    preexisting_id = state.get("published_post_id") or ""

    async with async_session_factory() as db:
        result = await db.execute(
            select(ContentPost).where(ContentPost.id == uuid.UUID(content_post_id))
        )
        post = result.scalar_one_or_none()

        if not post:
            raise ValueError(f"ContentPost {content_post_id} not found")

        if post.status not in (ContentStatus.APPROVED, ContentStatus.PUBLISHED):
            raise ValueError(
                f"ContentPost {content_post_id} has status '{post.status.value}', "
                "only 'approved' posts can be published"
            )

        # Guard against re-publishing an already-published post
        existing_published = await db.execute(
            select(PublishedPost).where(
                PublishedPost.content_post_id == post.id,
                PublishedPost.status == PublishStatus.PUBLISHED,
            )
        )
        if existing_published.scalar_one_or_none():
            raise ValueError(f"ContentPost {content_post_id} is already published")

        # Cancel any existing PENDING/PROCESSING records so a fresh publish can proceed.
        # This covers "Publish Now" on a post that was already scheduled.
        # Exclude the row we're about to use (when the API pre-created it).
        active_query = select(PublishedPost).where(
            PublishedPost.content_post_id == post.id,
            PublishedPost.status.in_(
                [PublishStatus.PENDING, PublishStatus.PROCESSING]
            ),
        )
        if preexisting_id:
            active_query = active_query.where(
                PublishedPost.id != uuid.UUID(preexisting_id)
            )
        active_records = (await db.execute(active_query)).scalars().all()

        if active_records:
            settings = get_settings()
            backend_url = settings.BACKEND_ORIGIN.rstrip("/")
            for old_pub in active_records:
                if old_pub.tiktok_publish_id:
                    try:
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.delete(
                                f"{backend_url}/v1/publisher/internal/cancel-scheduled/{old_pub.id}",
                                headers={"x-internal-api-key": settings.INTERNAL_API_KEY},
                            )
                    except Exception as exc:
                        logger.warning(
                            "resolve: could not cancel Zernio scheduled post",
                            published_post_id=str(old_pub.id),
                            error=str(exc),
                        )
                old_pub.status = PublishStatus.CANCELLED

        # Reuse pre-existing tracking record (created by the API handler) or create one.
        import uuid as _uuid

        _user_id_raw = state.get("user_id") or ""
        if preexisting_id:
            pub = (
                await db.execute(
                    select(PublishedPost).where(
                        PublishedPost.id == _uuid.UUID(preexisting_id)
                    )
                )
            ).scalar_one_or_none()
            if pub is None:
                raise ValueError(
                    f"PublishedPost {preexisting_id} not found"
                )
            pub.publish_mode = PublishMode(publish_mode)
            pub.status = PublishStatus.PROCESSING
            pub.privacy_level = state.get("privacy_level", pub.privacy_level)
        else:
            pub = PublishedPost(
                content_post_id=post.id,
                published_by=_uuid.UUID(_user_id_raw) if _user_id_raw else None,
                publish_mode=PublishMode(publish_mode),
                status=PublishStatus.PROCESSING,
                privacy_level=state.get("privacy_level", "PUBLIC_TO_EVERYONE"),
            )
            db.add(pub)
            await db.flush()
        published_post_id = str(pub.id)

        # Assemble caption
        hashtags = post.hashtags or []
        caption = assemble_caption(
            caption=post.caption,
            hashtags=hashtags,
            cta=post.cta,
        )
        pub.assembled_caption = caption

        # Resolve the media URL depending on content type.
        # Photo path (default): image_path is a Cloudinary https URL — reject anything else.
        # Video path: load the linked VideoClip and get its storage_url.
        post_content_type = getattr(post, "content_type", "photo") or "photo"
        video_url = ""
        if post_content_type == "video":
            from app.db.models.video_clip import VideoClip
            clip_result = await db.execute(
                select(VideoClip).where(VideoClip.content_post_id == post.id)
            )
            video_clip = clip_result.scalar_one_or_none()
            if not video_clip:
                raise ValueError(
                    f"ContentPost {content_post_id} is a video post but has no linked VideoClip"
                )
            video_url = video_clip.storage_url
            assert_cloudinary_url(video_url)
            image_public_url = ""
        else:
            image_public_url = post.image_path or ""
            assert_cloudinary_url(image_public_url)

        await db.commit()

    logger.info(
        "resolve: validated",
        content_post_id=content_post_id,
        published_post_id=published_post_id,
        content_type=post_content_type,
        media_url=(video_url or image_public_url)[:80],
    )

    return {
        "published_post_id": published_post_id,
        "assembled_caption": caption,
        "image_public_url": image_public_url,
        "content_type": post_content_type,
        "video_url": video_url,
    }


def _route_after_schedule(state: PublishPostState) -> str:
    """Conditional edge: always run publish_node; it forwards scheduledAt if set."""
    return "publish"


def build_publish_graph() -> StateGraph:
    """Build and compile the Publish Post Agent graph."""
    graph = StateGraph(PublishPostState)

    graph.add_node("resolve_and_validate", resolve_and_validate_node)
    graph.add_node("golden_hour", golden_hour_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("publish", publish_node)

    graph.add_edge(START, "resolve_and_validate")
    graph.add_edge("resolve_and_validate", "golden_hour")
    graph.add_edge("golden_hour", "scheduler")
    graph.add_edge("scheduler", "publish")
    graph.add_edge("publish", END)

    return graph.compile()
