"""Phase 1: Strategy Alignment — Read inputs, produce content plan."""

import json
import uuid

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.agents.post_generator.prompts import STRATEGY_ALIGNMENT_SYSTEM_PROMPT
from app.agents.post_generator.state import PostGenState
from app.clients.openai_client import get_content_gen_llm
from app.core.storage import get_storage
from app.db.models import ScanRun, TrendItem
from app.db.session import async_session_factory

logger = structlog.get_logger()


def _parse_json_response(content: str) -> dict | list:
    """Extract JSON from LLM response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def _load_analyzed_trends(scan_run_id: str) -> list[dict]:
    """Load analyzed TrendItems from DB for a completed scan run."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(TrendItem)
            .where(TrendItem.scan_run_id == uuid.UUID(scan_run_id))
            .order_by(TrendItem.relevance_score.desc().nullslast())
        )
        items = result.scalars().all()

        trends = []
        for item in items:
            trends.append({
                "title": item.title,
                "description": item.description,
                "source_url": item.source_url,
                "platform": item.platform,
                "category": item.category,
                "sentiment": item.sentiment.value if item.sentiment else None,
                "lifecycle": item.lifecycle.value if item.lifecycle else None,
                "relevance_score": item.relevance_score,
                "quality_score": item.quality_score,
                "engagement_prediction": (
                    item.engagement_prediction.value if item.engagement_prediction else None
                ),
                "source_type": item.source_type.value if item.source_type else None,
                "content_angles": item.content_angles or [],
                "key_data_points": item.key_data_points or [],
                "target_audience": item.target_audience or [],
                "cleaned_content": item.cleaned_content,
                "likes": item.likes,
                "comments_count": item.comments_count,
                "author_name": item.author_name,
                "published_at": str(item.published_at) if item.published_at else None,
                "trend_item_id": str(item.id),
                "is_promoted": item.is_promoted,
            })
        return trends


async def _load_trend_report(scan_run_id: str) -> str:
    """Load the trend report markdown from storage."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
        )
        scan_run = result.scalar_one_or_none()

        if not scan_run or not scan_run.report_file_path:
            return ""

        storage = get_storage()
        try:
            return storage.read_text(scan_run.report_file_path)
        except Exception as e:
            logger.warning(
                "Failed to load trend report",
                path=scan_run.report_file_path,
                error=str(e),
            )
            return ""


def _load_strategy() -> dict:
    """Load strategy from storage, falling back to default."""
    storage = get_storage()
    try:
        content = storage.read_text("strategy/default_strategy.json")
        return json.loads(content)
    except Exception as e:
        logger.warning("Failed to load strategy, using defaults", error=str(e))
        return {
            "version": "1.0",
            "brand_voice": {
                "tone": "professional yet approachable",
                "personality": ["insightful", "data-driven", "forward-thinking"],
                "avoid": ["hype language", "clickbait", "excessive jargon"],
                "tiktok_persona": "Tech content creator sharing bite-sized insights",
            },
            "content_preferences": {
                "preferred_formats": ["quick_tips", "trending_breakdown"],
                "min_data_points_per_post": 1,
                "max_emojis": 8,
                "cta_style": "action",
                "hashtag_count": {"min": 5, "max": 8},
            },
            "posting_insights": {
                "best_days": ["Tuesday", "Wednesday", "Thursday"],
                "best_times": ["8:00-10:00 AM", "12:00-1:00 PM"],
                "timezone": "Asia/Ho_Chi_Minh",
                "frequency": "3-5 posts per week",
            },
        }


async def strategy_alignment_node(state: PostGenState) -> dict:
    """Phase 1: Load inputs, call LLM to produce content plan."""
    scan_run_id = state["scan_run_id"]
    options = state.get("options", {})
    num_posts = options.get("num_posts", 3)

    logger.info("strategy_alignment: starting", scan_run_id=scan_run_id)

    # Load inputs
    analyzed_trends = await _load_analyzed_trends(scan_run_id)
    trend_report_md = await _load_trend_report(scan_run_id)
    strategy = _load_strategy()

    if not analyzed_trends:
        logger.warning("strategy_alignment: no analyzed trends found")
        return {
            "analyzed_trends": [],
            "trend_report_md": "",
            "strategy": strategy,
            "content_plan": [],
            "errors": [{"node": "strategy_alignment", "error": "No analyzed trends found"}],
        }

    # Cap num_posts to available trends (1 post per trend)
    effective_num_posts = min(num_posts, len(analyzed_trends))
    if effective_num_posts < num_posts:
        logger.warning(
            "strategy_alignment: capping num_posts to available trends",
            requested=num_posts,
            available_trends=len(analyzed_trends),
            effective=effective_num_posts,
        )

    # Build format restriction from options
    formats = options.get("formats")
    format_restriction = ""
    if formats:
        format_restriction = (
            f"- ONLY use these formats: {', '.join(formats)}. "
            "You may use each format multiple times to reach the target count."
        )

    # Build user message with all inputs
    trends_json = json.dumps(analyzed_trends, indent=2, default=str)
    strategy_json = json.dumps(strategy, indent=2)

    user_content = (
        f"## Trend Report\n\n{trend_report_md}\n\n"
        f"## Processed Articles ({len(analyzed_trends)} items)\n\n{trends_json}\n\n"
        f"## Content Strategy\n\n{strategy_json}"
    )

    system_prompt = STRATEGY_ALIGNMENT_SYSTEM_PROMPT.format(
        num_posts=effective_num_posts,
        format_restriction=format_restriction,
    )

    llm = get_content_gen_llm()
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        result = _parse_json_response(response.content)
        content_plan = result.get("content_plan", result) if isinstance(result, dict) else result

        # Validate: retry once if LLM returned fewer items than requested
        if len(content_plan) < effective_num_posts:
            deficit = effective_num_posts - len(content_plan)
            logger.warning(
                "strategy_alignment: content plan short, retrying for additional items",
                requested=effective_num_posts,
                received=len(content_plan),
                deficit=deficit,
            )

            existing_plan_json = json.dumps(content_plan, indent=2)
            retry_content = (
                f"You produced {len(content_plan)} posts but I need exactly "
                f"{effective_num_posts}.\n"
                f"Generate {deficit} MORE content plan items to add to the existing plan.\n"
                f"Each new item MUST use a different trend from the existing items.\n"
                f"Here is the existing plan (do NOT reuse the same trends):\n"
                f"{existing_plan_json}\n\n"
                f"Return ONLY a JSON object with a \"content_plan\" array of "
                f"the {deficit} NEW items."
            )

            retry_response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
                HumanMessage(content=retry_content),
            ])

            additional = _parse_json_response(retry_response.content)
            additional_items = (
                additional.get("content_plan", additional)
                if isinstance(additional, dict)
                else additional
            )
            content_plan.extend(additional_items)
            content_plan = content_plan[:effective_num_posts]

            if len(content_plan) < effective_num_posts:
                logger.warning(
                    "strategy_alignment: still short after retry",
                    final_count=len(content_plan),
                    requested=effective_num_posts,
                )

        logger.info(
            "strategy_alignment: content plan created",
            num_posts_planned=len(content_plan),
        )

        return {
            "analyzed_trends": analyzed_trends,
            "trend_report_md": trend_report_md,
            "strategy": strategy,
            "content_plan": content_plan,
        }

    except Exception as e:
        logger.error("strategy_alignment: LLM call failed", error=str(e))
        return {
            "analyzed_trends": analyzed_trends,
            "trend_report_md": trend_report_md,
            "strategy": strategy,
            "content_plan": [],
            "errors": [{"node": "strategy_alignment", "error": str(e)}],
        }
