import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import TrendScanState
from app.clients.openai_client import get_llm
from app.core.dedup import compute_dedup_key, titles_are_similar

logger = structlog.get_logger()

ANALYZER_SYSTEM_PROMPT = """You are a Technology trend analysis expert focused on the TikTok tech audience. You receive trending data from Hacker News and must analyze each item for its relevance to tech enthusiasts, developers, students, and Gen-Z professionals on TikTok.

For each trending item, provide:

1. **category**: One of: tech, business, education, other
   Focus on technology-related categorization since the data comes from Hacker News.

2. **sentiment**: One of: positive, negative, neutral, mixed

3. **lifecycle**: One of: rising (new/gaining traction), peak (maximum popularity), declining (losing momentum)

4. **relevance_score**: Float 0-10 indicating relevance for TikTok technology content. Consider:
   - Relevance to tech enthusiasts and developers on TikTok
   - Engagement metrics (HN score, comments)
   - Timeliness and novelty
   - Potential for TikTok content creation (quick tips, hot takes, trending breakdowns, myth busting)

5. **related_topics**: List of 2-5 related technology topics or keywords relevant to TikTok tech audience

Return a JSON array where each object has:
{
  "index": <original item index>,
  "category": "...",
  "sentiment": "...",
  "lifecycle": "...",
  "relevance_score": 0-10,
  "related_topics": ["...", "..."]
}

Be accurate and consistent. Analyze ALL items provided. Prioritize items that would resonate with a TikTok tech-curious audience — surprising, shareable, and visually interesting topics."""


def _chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


async def analyzer_node(state: TrendScanState) -> dict:
    """Analyze raw trend data using LLM for categorization, sentiment, and scoring."""
    raw_results = state.get("raw_results", [])

    # Flatten all items with platform tags
    all_items = []
    for result in raw_results:
        if result["error"] is None:
            for item in result["items"]:
                item["_platform"] = result["platform"]
                all_items.append(item)

    if not all_items:
        logger.warning("Analyzer: no items to analyze")
        return {"analyzed_trends": [], "cross_platform_groups": []}

    logger.info("Analyzer: starting analysis", total_items=len(all_items))

    llm = get_llm()
    analyzed = []

    # Process in chunks of 40 to fit context window
    for chunk_idx, chunk in enumerate(_chunks(all_items, 40)):
        # Prepare condensed items for the LLM (strip raw_data to save tokens)
        condensed = []
        for i, item in enumerate(chunk):
            condensed.append({
                "index": i,
                "title": item.get("title", "")[:200],
                "description": (item.get("description") or "")[:300],
                "platform": item.get("_platform", "unknown"),
                "hashtags": item.get("hashtags", [])[:10],
                "views": item.get("views"),
                "likes": item.get("likes"),
                "comments_count": item.get("comments_count"),
                "shares": item.get("shares"),
            })

        try:
            response = await llm.ainvoke([
                SystemMessage(content=ANALYZER_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"Analyze these {len(condensed)} trending items (chunk {chunk_idx + 1}):\n\n{json.dumps(condensed, default=str)}"
                ),
            ])

            # Parse LLM response
            content = response.content
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            analysis_results = json.loads(content.strip())

            # Merge analysis back into items
            analysis_map = {a["index"]: a for a in analysis_results}
            for i, item in enumerate(chunk):
                analysis = analysis_map.get(i, {})
                item["category"] = analysis.get("category", "other")
                item["sentiment"] = analysis.get("sentiment", "neutral")
                item["lifecycle"] = analysis.get("lifecycle", "rising")
                item["relevance_score"] = analysis.get("relevance_score", 5.0)
                item["related_topics"] = analysis.get("related_topics", [])
                item["dedup_key"] = compute_dedup_key(item.get("title", ""))
                analyzed.append(item)

        except Exception as e:
            logger.error("Analyzer: LLM analysis failed for chunk", chunk=chunk_idx, error=str(e))
            # Fall back: add items without analysis
            for item in chunk:
                item["category"] = "other"
                item["sentiment"] = "neutral"
                item["lifecycle"] = "rising"
                item["relevance_score"] = 5.0
                item["related_topics"] = []
                item["dedup_key"] = compute_dedup_key(item.get("title", ""))
                analyzed.append(item)

    # Cross-platform grouping
    groups = _detect_cross_platform_groups(analyzed)

    logger.info(
        "Analyzer: completed",
        analyzed_count=len(analyzed),
        cross_platform_groups=len(groups),
    )

    return {
        "analyzed_trends": analyzed,
        "cross_platform_groups": groups,
    }


def _detect_cross_platform_groups(items: list[dict]) -> list[dict]:
    """Group items that represent the same trend across platforms."""
    groups = []
    used = set()

    for i, item_a in enumerate(items):
        if i in used:
            continue

        group = {
            "representative_title": item_a.get("title", ""),
            "platforms": [item_a.get("_platform", "unknown")],
            "item_indices": [i],
            "combined_score": item_a.get("relevance_score", 0),
        }

        for j, item_b in enumerate(items[i + 1 :], start=i + 1):
            if j in used:
                continue
            if item_a.get("_platform") == item_b.get("_platform"):
                continue

            if titles_are_similar(
                item_a.get("title", ""), item_b.get("title", ""), threshold=0.5
            ):
                group["platforms"].append(item_b.get("_platform", "unknown"))
                group["item_indices"].append(j)
                group["combined_score"] += item_b.get("relevance_score", 0)
                used.add(j)

        if len(group["platforms"]) > 1:
            # Boost score for cross-platform trends
            group["combined_score"] *= 1.0 + (len(group["platforms"]) * 0.2)
            groups.append(group)
            used.add(i)

    return groups
