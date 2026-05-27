"""Post Generation Agent — entry point for running the pipeline."""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.agents.post_generator.graph import build_post_gen_graph
from app.agents.post_generator.state import PostGenState
from app.db.models import ScanRun, ScanStatus
from app.db.session import async_session_factory

logger = structlog.get_logger()


_NODE_LABELS: dict[str, str] = {
    "strategy_alignment":    "Planning Strategy",
    "content_generation":    "Writing Posts",
    "image_prompt_creation": "Generating Image Prompts",
    "image_generation":      "Generating Images",
    "auto_review":           "Reviewing Posts",
    "output_packaging":      "Finalizing",
}


def _friendly_post_gen_error(errors: list[dict], total_posts: int = 0) -> str:
    """Return a concise, user-facing error message from the pipeline errors list."""
    if not errors:
        return ""
    first = errors[0]
    node = first.get("node", "unknown")
    raw = first.get("error", "unknown error").lower()

    label = _NODE_LABELS.get(node, node.replace("_", " "))

    if "insufficient_quota" in raw or "exceeded your current quota" in raw:
        detail = "OpenAI quota exceeded — check your API billing plan"
    elif "rate_limit" in raw or "429" in raw:
        detail = "OpenAI rate limit hit — try again in a few minutes"
    elif "timeout" in raw or "timed out" in raw:
        detail = "Request timed out — try again"
    elif "invalid_api_key" in raw or "api key" in raw:
        detail = "Invalid OpenAI API key"
    else:
        detail = "An unexpected error occurred. Please try again later or contact your administrator for support."

    extra = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    if total_posts > 0:
        return f"{label}: {detail}{extra} — {total_posts} post(s) still generated"
    return f"{label} failed: {detail}{extra}"


# Maps post-gen node names to step identifiers for real-time progress reporting.
_POST_GEN_STEP_MAP: dict[str, str] = {
    "strategy_alignment":    "post_strategy",
    "content_generation":    "post_content",
    "image_prompt_creation": "post_image_prompts",
    "image_generation":      "post_images",
    "auto_review":           "post_review",
    "output_packaging":      "post_packaging",
}


async def _save_post_gen_error(
    scan_run_id: str,
    errors: list[dict],
    total_posts: int = 0,
) -> None:
    """Persist a user-friendly error + the failed step to ScanRun."""
    message = _friendly_post_gen_error(errors, total_posts)
    failed_node = errors[0].get("node", "") if errors else ""
    failed_step = _POST_GEN_STEP_MAP.get(failed_node, "")
    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id)))
            ).scalar_one_or_none()
            if row:
                row.error = message
                # Any error means the run is not fully successful.
                row.status = ScanStatus.PARTIAL
                if failed_step:
                    row.current_step = failed_step
                await db.commit()
    except Exception as exc:
        logger.warning("_save_post_gen_error failed", scan_run_id=scan_run_id, exc=str(exc))


async def run_post_generation(
    scan_run_id: str,
    options: dict | None = None,
    user_id: str | None = None,
    step_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """Execute the post generation pipeline for a completed scan run.

    Args:
        scan_run_id: UUID of the completed scan run to generate posts for.
        options: Optional configuration:
            - num_posts: Number of posts to generate (default 3, max 10)
            - formats: List of allowed post formats (default: all)
        user_id: UUID of the user triggering generation — propagated
            through LangGraph state so persisted ContentPost rows carry
            the owning user.

    Returns:
        The final_output dict containing content_plan, posts, and strategy_update.

    Raises:
        ValueError: If scan_run_id is invalid or scan run is not completed.
    """
    start_time = time.time()
    options = options or {}

    logger.info(
        "post_generation: starting",
        scan_run_id=scan_run_id,
        user_id=user_id,
        options=options,
    )

    # Validate scan run exists and is completed
    async with async_session_factory() as db:
        result = await db.execute(
            select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
        )
        scan_run = result.scalar_one_or_none()

        if not scan_run:
            raise ValueError(f"Scan run not found: {scan_run_id}")

        if scan_run.status not in (ScanStatus.COMPLETED, ScanStatus.PARTIAL, ScanStatus.RUNNING):
            raise ValueError(
                f"Scan run {scan_run_id} is not completed "
                f"(status: {scan_run.status.value})"
            )

    # Build and run the graph
    graph = build_post_gen_graph()

    initial_state = PostGenState(
        scan_run_id=scan_run_id,
        user_id=user_id,
        options={
            "num_posts": min(options.get("num_posts", 3), 10),
            "formats": options.get("formats"),
        },
        trend_report_md="",
        analyzed_trends=[],
        strategy={},
        content_plan=[],
        generated_posts=[],
        review_results=[],
        revision_count=0,
        posts_to_revise=[],
        final_output={},
        saved_file_paths=[],
        errors=[],
    )

    try:
        if step_callback:
            # Stream events to report each sub-stage; accumulate node outputs as final state.
            # When a node returns errors, persist immediately and freeze current_step at
            # the failed node so the UI flips to error state on the next ~2s poll.
            final_state: dict = {}
            _last: str | None = None
            _error_persisted = False
            async for event in graph.astream_events(initial_state, version="v2"):
                if event["event"] == "on_chain_start":
                    if _error_persisted:
                        continue  # Don't advance step past the failed node
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    step = _POST_GEN_STEP_MAP.get(node)
                    if step and step != _last:
                        _last = step
                        await step_callback(step)
                elif event["event"] == "on_chain_end":
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node in _POST_GEN_STEP_MAP:
                        output = event.get("data", {}).get("output", {})
                        if isinstance(output, dict):
                            final_state.update(output)
                            node_errors = output.get("errors") or []
                            if node_errors and not _error_persisted:
                                await _save_post_gen_error(scan_run_id, node_errors, 0)
                                _error_persisted = True
        else:
            final_state = await graph.ainvoke(initial_state)

        duration_ms = int((time.time() - start_time) * 1000)
        final_output = final_state.get("final_output", {})
        errors = final_state.get("errors", [])

        total_posts = len(final_output.get("posts", []))

        if errors:
            await _save_post_gen_error(scan_run_id, errors, total_posts)
            logger.warning(
                "post_generation: completed with errors",
                scan_run_id=scan_run_id,
                duration_ms=duration_ms,
                total_posts=total_posts,
                errors=len(errors),
            )
        else:
            logger.info(
                "post_generation: completed",
                scan_run_id=scan_run_id,
                duration_ms=duration_ms,
                total_posts=total_posts,
            )

        return final_output

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "post_generation: failed",
            scan_run_id=scan_run_id,
            duration_ms=duration_ms,
            error=str(e),
        )
        raise
