"""Combined trend analysis + report generation node.

Single-pass LLM call that scores, filters, analyzes, and generates
a TikTok-focused trend report from raw crawled articles.
"""

import json
from datetime import datetime, timezone

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import TrendScanState
from app.clients.openai_client import get_analyzer_llm
from app.core.dedup import compute_dedup_key
from app.core.storage import get_storage

logger = structlog.get_logger()

DEFAULT_QUALITY_THRESHOLD = 5
DEFAULT_KEYWORDS = [
    "Artificial Intelligence & Machine Learning",
    "Software Engineering & Developer Tools",
    "Cloud Computing & Infrastructure",
    "Cybersecurity & Privacy",
    "Open Source Projects",
    "Startups & Tech Industry",
    "Hardware & Semiconductors",
    "Programming Languages & Frameworks",
    "Data Science & Analytics",
    "Robotics & Automation",
]

TREND_ANALYZER_SYSTEM_PROMPT = """You are a Senior Tech Industry Analyst powering a TikTok content AI system. You receive raw crawled articles about technology trends. Your audience is TikTok — tech enthusiasts, developers, students, Gen-Z professionals, and curious learners.

Your job has 2 phases in ONE pass.

---

## PHASE 1: PREPROCESSING & DEEP ANALYSIS

### Step 1 — Quality Scoring (1-10)

Rate each article on these tech-specific criteria:

| Criteria | What to check | Weight |
|---|---|---|
| **Signal vs Noise** | Is this a real tech insight, product launch, research finding, industry shift — or just a repost, listicle filler, or SEO spam? | 30% |
| **Substantive Depth** | Does it contain technical detail, data points, expert quotes, or original analysis — or is it surface-level? (< 100 words of actual content = auto-fail) | 30% |
| **Recency & Relevance** | Is it about a current development matching the target keywords? Outdated or tangential = penalize. | 20% |
| **Source Authority** | From a credible tech source (official blog, reputable publication, research paper, industry report)? Or from content farms, aggregator spam? | 20% |

Score guide:
- 1-3: Junk — broken page, irrelevant, content farm, error page
- 4-5: Low value — shallow, outdated, or barely relevant
- 6-7: Usable — decent insight but not standout
- 8-10: High value — strong signal, original data, expert perspective

**Discard any article scoring below {quality_threshold}.**

### Step 2 — Deep Analysis (passing articles only)

For each surviving article:

- `sentiment`: bullish | neutral | bearish | controversial
  (Use tech-industry sentiment — "bullish" = optimistic about adoption/growth, "bearish" = skeptical/declining, "controversial" = polarizing debate)

- `engagement_prediction`: low | medium | high | viral
  Predict TikTok engagement based on:
  - Is it shareable and visually interesting? (high engagement)
  - Is it a "hot take" or surprising/contrarian topic? (viral potential)
  - Is it too niche/dry for broad TikTok audience? (low)
  - Does it have a "mind-blowing fact" or "myth-busting" angle? (viral on TikTok)

- `lifecycle`: emerging | rising | peaking | saturated | declining
  (5-stage for better granularity in tech where trends move fast)

- `content_angles`: 3 content angles specifically optimized for TikTok, each with:
  - `angle`: the content hook (max 15 words)
  - `format`: quick_tips | trending_breakdown | hot_take | did_you_know | tutorial_hack | myth_busters | behind_the_tech
  - `hook_line`: a compelling TikTok opening line (the "scroll-stopper", max 15 words)

- `cleaned_content`: extract ONLY valuable paragraphs — strip nav, ads, cookie banners, sidebars, author bios, related articles, broken HTML. Keep: core arguments, data points, quotes, technical details.

- `key_data_points`: extract up to 5 specific numbers, statistics, or quantifiable claims (these are gold for TikTok posts)

- `source_type`: classify the article source as exactly one of: official_blog, news, research, community, social
  (Do NOT invent new values. Use "official_blog" for company/project blogs, "news" for media outlets, "research" for papers/reports, "community" for forums/discussions, "social" for social media posts.)

### CRITICAL — Enum value constraints
All enum fields MUST use EXACTLY one of the listed values. Do NOT abbreviate, paraphrase, or invent new values.
- `sentiment`: bullish | neutral | bearish | controversial
- `engagement_prediction`: low | medium | high | viral
- `lifecycle`: emerging | rising | peaking | saturated | declining
- `source_type`: official_blog | news | research | community | social
- `content_angles[].format`: quick_tips | trending_breakdown | hot_take | did_you_know | tutorial_hack | myth_busters | behind_the_tech

---

## PHASE 2: REPORT GENERATION

Using ONLY passing articles, generate:

### Output A — Trend Report (Markdown)

```md
# Tech Trend Report — {date}
**Keywords:** {keywords}
**Target Platform:** TikTok
**Articles Analyzed:** X passed / Y total

## Executive Summary
(3-5 sentences: what's happening in tech this cycle, dominant narrative, biggest opportunity for TikTok content)

## Trend Ranking

| # | Trend | Score | Sentiment | Lifecycle | TikTok Potential | Best Angle |
|---|---|---|---|---|---|---|

## Deep Dives
(For each top trend:)
### [Trend Name]
- **Why it matters now:** (2-3 sentences)
- **Key data points:** (bullet list of hard numbers)
- **TikTok audience fit:** Who cares about this — developers? students? tech enthusiasts? Gen-Z professionals?
- **Timing window:** How long is this trend relevant for content?
- **Recommended angles:**
  1. [Format] — [Angle] — Hook: "[hook_line]"
  2. [Format] — [Angle] — Hook: "[hook_line]"

## Content Calendar Suggestions
(5-7 prioritized post ideas, ordered by predicted engagement)
| Priority | Topic | Format | Best Post Day | Hook |
|---|---|---|---|---|

TikTok posting guidance:
- Evenings and weekends get highest engagement on TikTok
- Hot takes and did-you-know formats go viral fastest on TikTok
- Posts with surprising stats in the hook get massive saves and shares
- Quick tips with 4-5 key points perform consistently well
```

### Output B — Processed Articles (JSON array)
For each passing article:
```json
{{
  "id": "<article_id>",
  "title": "<cleaned title>",
  "source_url": "<url>",
  "source_type": "<MUST be exactly one of: official_blog, news, research, community, social>",
  "quality_score": <number>,
  "cleaned_content": "<extracted core content>",
  "key_data_points": ["<stat1>", "<stat2>"],
  "sentiment": "<bullish|neutral|bearish|controversial>",
  "engagement_prediction": "<low|medium|high|viral>",
  "lifecycle": "<emerging|rising|peaking|saturated|declining>",
  "content_angles": [
    {{
      "angle": "<content hook>",
      "format": "<format_type>",
      "hook_line": "<scroll-stopper opening>"
    }}
  ],
  "target_audience": ["developers", "students", "tech_enthusiasts", "gen_z_professionals", "general_tech"]
}}
```

### Output C — Discarded Articles (JSON array)
```json
{{
  "id": "<article_id>",
  "title": "<raw title>",
  "quality_score": <number>,
  "discard_reason": "<brief reason>"
}}
```

---

## RESPONSE FORMAT

Return a single JSON object:
```json
{{
  "trend_report_md": "<full markdown string>",
  "processed_articles": [ ... ],
  "discarded_articles": [ ... ],
  "meta": {{
    "total_input": <number>,
    "passed": <number>,
    "discarded": <number>,
    "dominant_sentiment": "<string>",
    "top_trend": "<string>",
    "top_tiktok_format": "<most recommended format this cycle>",
    "suggested_posting_window": "<e.g. evenings 6-9pm>"
  }}
}}
```

Respond ONLY with the JSON object. No preamble, no markdown fences, no explanation."""


def _prepare_raw_articles(all_items: list[dict]) -> list[dict]:
    """Condense raw items into the format expected by the LLM prompt."""
    articles = []
    for i, item in enumerate(all_items):
        raw = item.get("raw_data", {})
        articles.append({
            "id": str(i),
            "title": item.get("title", "")[:300],
            "url": item.get("source_url", ""),
            "raw_content": (item.get("content_body") or item.get("description") or "")[:3000],
            "platform": item.get("_platform", "hackernews"),
            "crawled_at": item.get("published_at", ""),
            "hn_score": raw.get("hn_score", 0),
            "hn_comments": raw.get("hn_comments", 0),
        })
    return articles


def _parse_llm_response(content: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


def _merge_analysis_into_items(
    all_items: list[dict],
    processed_articles: list[dict],
) -> list[dict]:
    """Merge LLM analysis results back into the original item dicts."""
    # Build lookup by article id (which is the original index)
    analysis_map = {}
    for article in processed_articles:
        article_id = str(article.get("id", ""))
        analysis_map[article_id] = article

    analyzed = []
    for i, item in enumerate(all_items):
        analysis = analysis_map.get(str(i))
        if analysis is None:
            continue  # Discarded by quality threshold

        item["category"] = "tech"  # All passing articles are tech-relevant
        item["sentiment"] = analysis.get("sentiment", "neutral")
        item["engagement_prediction"] = analysis.get("engagement_prediction", "medium")
        item["lifecycle"] = analysis.get("lifecycle", "rising")
        item["relevance_score"] = analysis.get("quality_score", 5.0)
        item["quality_score"] = analysis.get("quality_score", 5.0)
        item["content_angles"] = analysis.get("content_angles", [])
        item["key_data_points"] = analysis.get("key_data_points", [])
        item["target_audience"] = analysis.get("target_audience", [])
        item["source_type"] = analysis.get("source_type", "community")
        item["cleaned_content"] = analysis.get("cleaned_content", "")
        item["related_topics"] = [
            angle.get("angle", "") for angle in analysis.get("content_angles", [])
        ]
        item["dedup_key"] = compute_dedup_key(item.get("title", ""))
        analyzed.append(item)

    return analyzed


def _save_report_files(
    scan_run_id: str,
    report_markdown: str,
    summary_data: dict,
) -> str:
    """Save report.md and summary.json via storage backend.

    Returns the relative key (used as report_file_path in DB).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    storage = get_storage()

    report_key = f"reports/{scan_run_id}/{today}_report.md"
    summary_key = f"reports/{scan_run_id}/{today}_summary.json"

    storage.write_text(report_key, report_markdown, content_type="text/markdown")
    storage.write_text(
        summary_key,
        json.dumps(summary_data, indent=2, ensure_ascii=False, default=str),
        content_type="application/json",
    )

    logger.info(
        "Report files saved",
        report_key=report_key,
        summary_key=summary_key,
    )
    return report_key


def _generate_fallback_report(all_items: list[dict]) -> dict:
    """Generate a minimal fallback when the LLM call fails."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Tech Trend Report — {today}",
        f"**Articles Analyzed:** 0 passed / {len(all_items)} total",
        "",
        "## Executive Summary",
        "Report generation failed. Raw data preserved for manual review.",
        "",
        "## Trend Ranking",
        "",
        "| # | Trend | Score |",
        "|---|---|---|",
    ]
    for i, item in enumerate(all_items[:20], 1):
        lines.append(f"| {i} | {item.get('title', 'Unknown')[:80]} | N/A |")

    fallback_processed = []
    for i, item in enumerate(all_items):
        fallback_processed.append({
            "id": str(i),
            "title": item.get("title", ""),
            "source_url": item.get("source_url", ""),
            "source_type": "community",
            "quality_score": 5.0,
            "cleaned_content": item.get("content_body", ""),
            "key_data_points": [],
            "sentiment": "neutral",
            "engagement_prediction": "medium",
            "lifecycle": "rising",
            "content_angles": [],
            "target_audience": ["general_tech"],
        })

    return {
        "trend_report_md": "\n".join(lines),
        "processed_articles": fallback_processed,
        "discarded_articles": [],
        "meta": {
            "total_input": len(all_items),
            "passed": len(all_items),
            "discarded": 0,
            "dominant_sentiment": "neutral",
            "top_trend": all_items[0].get("title", "Unknown") if all_items else "N/A",
            "top_tiktok_format": "quick_tips",
            "suggested_posting_window": "Tue-Thu 8-10am",
        },
    }


def _chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


async def trend_analyzer_node(state: TrendScanState) -> dict:
    """Combined analysis + report generation in a single LLM pass.

    Quality scores articles, discards below threshold, performs deep
    TikTok-focused analysis, and generates a trend report — all in one call.
    """
    raw_results = state.get("raw_results", [])
    scan_run_id = state.get("scan_run_id", "unknown")
    options = state.get("options", {})

    quality_threshold = options.get("quality_threshold", DEFAULT_QUALITY_THRESHOLD)
    keywords = options.get("keywords", DEFAULT_KEYWORDS)

    # Flatten all items with platform tags
    all_items = []
    for result in raw_results:
        if result["error"] is None:
            for item in result["items"]:
                item["_platform"] = result["platform"]
                all_items.append(item)

    if not all_items:
        logger.warning("TrendAnalyzer: no items to analyze")
        return {
            "analyzed_trends": [],
            "discarded_articles": [],
            "trend_report_md": "",
            "analysis_meta": {},
            "report_file_path": "",
        }

    logger.info("TrendAnalyzer: starting combined analysis + report", total_items=len(all_items))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    llm = get_analyzer_llm()

    # For large batches, process in chunks and merge
    all_processed = []
    all_discarded = []
    all_report_sections = []
    final_meta = {}

    for chunk_idx, chunk in enumerate(_chunks(all_items, 40)):
        raw_articles = _prepare_raw_articles(chunk)

        system_prompt = TREND_ANALYZER_SYSTEM_PROMPT.format(
            quality_threshold=quality_threshold,
            date=today,
            keywords=json.dumps(keywords),
        )

        user_message = json.dumps(raw_articles, default=str)

        try:
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ])

            result = _parse_llm_response(response.content)

            chunk_processed = result.get("processed_articles", [])
            chunk_discarded = result.get("discarded_articles", [])
            chunk_report = result.get("trend_report_md", "")
            chunk_meta = result.get("meta", {})

            # Offset article IDs for chunks beyond the first
            offset = chunk_idx * 40
            for article in chunk_processed:
                article["id"] = str(int(article.get("id", "0")) + offset)
            for article in chunk_discarded:
                article["id"] = str(int(article.get("id", "0")) + offset)

            all_processed.extend(chunk_processed)
            all_discarded.extend(chunk_discarded)
            if chunk_report:
                all_report_sections.append(chunk_report)
            if not final_meta:
                final_meta = chunk_meta

            logger.info(
                "TrendAnalyzer: chunk processed",
                chunk=chunk_idx + 1,
                passed=len(chunk_processed),
                discarded=len(chunk_discarded),
            )

        except Exception as e:
            logger.error(
                "TrendAnalyzer: LLM call failed for chunk",
                chunk=chunk_idx,
                error=str(e),
            )
            # Fallback for this chunk
            fallback = _generate_fallback_report(chunk)
            offset = chunk_idx * 40
            for article in fallback["processed_articles"]:
                article["id"] = str(int(article.get("id", "0")) + offset)
            all_processed.extend(fallback["processed_articles"])
            if not all_report_sections:
                all_report_sections.append(fallback["trend_report_md"])

    # Use the first chunk's report as the main report (it has the full structure)
    # For multi-chunk scenarios, the first chunk report covers the top articles
    trend_report_md = all_report_sections[0] if all_report_sections else ""

    # Auto-promote discarded articles when post generation needs more trends.
    # Uses a retry loop (max 2 attempts) to handle LLM still discarding some articles.
    generate_posts = options.get("generate_posts", False)
    num_posts = options.get("num_posts", 0)

    if generate_posts and num_posts > 0 and len(all_processed) < num_posts and all_discarded:
        remaining_discarded = sorted(
            all_discarded,
            key=lambda d: d.get("quality_score", 0),
            reverse=True,
        )
        attempted_ids: set[str] = set()
        max_promotion_attempts = 2

        for attempt in range(max_promotion_attempts):
            if len(all_processed) >= num_posts or not remaining_discarded:
                break

            deficit = num_posts - len(all_processed)
            # Pick top candidates not yet attempted
            candidates = [
                d for d in remaining_discarded if d["id"] not in attempted_ids
            ][:deficit]

            if not candidates:
                break

            ids_to_promote = [d["id"] for d in candidates]
            attempted_ids.update(ids_to_promote)

            items_to_promote = [
                all_items[int(did)] for did in ids_to_promote
                if int(did) < len(all_items)
            ]

            if not items_to_promote:
                break

            logger.info(
                "TrendAnalyzer: promoting discarded articles",
                attempt=attempt + 1,
                deficit=deficit,
                promoting=len(items_to_promote),
            )

            try:
                promote_articles = _prepare_raw_articles(items_to_promote)
                promote_prompt = TREND_ANALYZER_SYSTEM_PROMPT.format(
                    quality_threshold=1,
                    date=today,
                    keywords=json.dumps(keywords),
                )
                promote_response = await llm.ainvoke([
                    SystemMessage(content=promote_prompt),
                    HumanMessage(content=json.dumps(promote_articles, default=str)),
                ])
                promote_result = _parse_llm_response(promote_response.content)
                promoted = promote_result.get("processed_articles", [])

                # Fix IDs back to original all_items indices and tag as promoted
                for article, orig_id in zip(promoted, ids_to_promote):
                    article["id"] = orig_id
                    article["_promoted"] = True

                all_processed.extend(promoted)

                # Remove all attempted IDs from remaining pool
                remaining_discarded = [
                    d for d in remaining_discarded if d["id"] not in attempted_ids
                ]

                logger.info(
                    "TrendAnalyzer: promoted articles",
                    attempt=attempt + 1,
                    promoted=len(promoted),
                    total_processed=len(all_processed),
                )
            except Exception as e:
                logger.error(
                    "TrendAnalyzer: promotion re-analysis failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                break

        # Update all_discarded to reflect removals
        all_discarded = [d for d in all_discarded if d["id"] not in attempted_ids]

    # Update meta with actual totals
    final_meta.update({
        "total_input": len(all_items),
        "passed": len(all_processed),
        "discarded": len(all_discarded),
    })

    # Merge analysis back into original items
    analyzed_items = _merge_analysis_into_items(all_items, all_processed)

    # Save report files
    report_file_path = ""
    if trend_report_md:
        summary_data = {
            "scan_run_id": scan_run_id,
            "meta": final_meta,
            "processed_count": len(all_processed),
            "discarded_count": len(all_discarded),
            "processed_articles": all_processed,
            "discarded_articles": all_discarded,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        report_file_path = _save_report_files(scan_run_id, trend_report_md, summary_data)

    logger.info(
        "TrendAnalyzer: completed",
        analyzed=len(analyzed_items),
        discarded=len(all_discarded),
        report_saved=bool(report_file_path),
    )

    return {
        "analyzed_trends": analyzed_items,
        "discarded_articles": all_discarded,
        "trend_report_md": trend_report_md,
        "analysis_meta": final_meta,
        "report_file_path": report_file_path,
    }
