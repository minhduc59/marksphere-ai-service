import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import TrendScanState
from app.clients.openai_client import get_report_llm

logger = structlog.get_logger()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # ai-service/
REPORTS_DIR = BASE_DIR / "reports"

REPORT_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích marketing cao cấp chuyên về TikTok và lĩnh vực Công Nghệ. Hãy viết TOÀN BỘ báo cáo bằng tiếng Việt chuyên nghiệp.
Báo cáo này sẽ được sử dụng để tạo nội dung TikTok trong lĩnh vực công nghệ — quick tips, trending breakdowns, hot takes, và tech insights.
Dữ liệu nguồn từ Hacker News — cộng đồng công nghệ hàng đầu thế giới.

Giữ nguyên tên công nghệ, thuật ngữ kỹ thuật, hashtag, URL, và các chỉ số dạng số bằng tiếng Anh gốc.

Tạo báo cáo Markdown với CHÍNH XÁC các phần sau theo thứ tự:

# Báo Cáo Xu Hướng Công Nghệ cho TikTok — {date}

## Tóm Tắt Tổng Quan
- 3-5 câu tổng quan về bối cảnh xu hướng công nghệ hiện tại từ Hacker News
- Nêu bật top 5 xu hướng, mỗi xu hướng một câu giải thích TẠI SAO chúng thu hút cộng đồng tech
- Một nhận định then chốt cho chiến lược nội dung TikTok

## Tổng Quan Thị Trường Công Nghệ
- Phân tích phân bố danh mục công nghệ (AI/ML, Web Dev, DevOps, Security, etc.)
- Tóm tắt phân tích cảm xúc (tâm trạng chung của cộng đồng tech)
- Các chủ đề mới nổi mà creator công nghệ cần theo dõi trên TikTok

## Bảng Xếp Hạng Xu Hướng

| Hạng | Tiêu Đề | Danh Mục | Điểm | Cảm Xúc | Vòng Đời | HN Score |
|------|---------|----------|------|---------|----------|----------|
(Bao gồm TẤT CẢ xu hướng, sắp xếp theo relevance_score giảm dần)

## Phân Tích Chi Tiết — Top 10 Xu Hướng

Với mỗi xu hướng trong top 10 theo relevance_score:

### {rank}. {title}
- **Điểm TikTok:** {score}/10 | **Vòng đời:** {lifecycle}
- **Danh mục:** {category} | **Cảm xúc:** {sentiment}
- **HN Engagement:** {hn_score} points, {comments} comments
- **Tại sao đang hot:** 2-3 câu phân tích tại sao xu hướng này thu hút cộng đồng tech
- **Cơ hội TikTok:** 1-2 câu về cách tạo nội dung TikTok từ xu hướng này

## Gợi Ý Nội Dung TikTok

Với mỗi xu hướng trong top 10, đề xuất 2-3 ý tưởng nội dung TikTok:

### {trend_title}
1. **{content_type}** trên **TikTok**
   - **Phong cách:** {writing_style}
   - **Câu mở đầu:** "{một câu mở đầu/hook cụ thể cho TikTok, sẵn sàng sử dụng}"
   - **Mức tương tác dự kiến:** {high/medium/low}
   - **Tại sao hiệu quả:** 1 câu giải thích lý do

Trong đó:
- content_type: một trong tiktok_video, tiktok_slideshow, tiktok_series, tiktok_duet, tiktok_stitch
- writing_style: một trong quick_tips, hot_take, storytelling, educational, data_driven
- Câu mở đầu: Phải là câu cụ thể, hấp dẫn cho đối tượng Gen-Z và tech enthusiast — KHÔNG dùng câu chung chung

YÊU CẦU QUAN TRỌNG:
- Tất cả gợi ý nội dung phải dành cho TikTok — KHÔNG đề xuất cho các nền tảng khác
- Tập trung vào lĩnh vực Công Nghệ — quick tips, trending breakdowns, myth busting, behind-the-tech
- Mọi câu mở đầu phải cụ thể và có thể sử dụng ngay — không dùng placeholder
- Lý giải điểm số phải tham chiếu đến HN score và comments khi có
- Nếu thiếu dữ liệu, hãy ghi nhận trung thực thay vì bịa số liệu"""

CONTENT_ANGLES_SYSTEM_PROMPT = """Bạn là chuyên gia chiến lược nội dung TikTok trong lĩnh vực Công Nghệ. Dựa trên các chủ đề trending từ Hacker News, hãy tạo các gợi ý góc nội dung TikTok có cấu trúc.

Viết các giá trị "hook" và "rationale" bằng tiếng Việt tự nhiên, phù hợp với đối tượng Gen-Z và tech enthusiast trên TikTok.
Giữ nguyên các giá trị enum (content_type, writing_style, estimated_engagement) bằng tiếng Anh.

Trả về CHỈ một mảng JSON hợp lệ. Không markdown, không giải thích, chỉ mảng JSON.

Mỗi phần tử phải có chính xác các trường sau:
{
  "trend_title": "tiêu đề chính xác của xu hướng",
  "platform": "tiktok",
  "content_type": "tiktok_video|tiktok_slideshow|tiktok_series|tiktok_duet|tiktok_stitch",
  "writing_style": "quick_tips|hot_take|storytelling|educational|data_driven",
  "hook": "Một câu mở đầu cụ thể, hấp dẫn cho TikTok, sẵn sàng sử dụng — viết bằng tiếng Việt",
  "estimated_engagement": "high|medium|low",
  "rationale": "Một câu giải thích tại sao góc nội dung này hiệu quả cho xu hướng này trên TikTok — viết bằng tiếng Việt"
}

Tạo 2-3 góc nội dung cho mỗi xu hướng. Mỗi góc nên sử dụng loại nội dung TikTok KHÁC NHAU.
Câu mở đầu phải cụ thể theo xu hướng — không dùng các cụm từ marketing chung chung.
Tập trung vào quick tips, trending breakdowns, myth busting, và behind-the-tech content."""


def _prepare_report_data(state: TrendScanState) -> dict:
    """Prepare analyzed trends for LLM report generation."""
    analyzed = state.get("analyzed_trends", [])
    cross_platform_groups = state.get("cross_platform_groups", [])

    # Sort by relevance_score descending
    sorted_trends = sorted(
        analyzed,
        key=lambda x: x.get("relevance_score", 0),
        reverse=True,
    )

    # Top 50 for detailed LLM analysis
    top_items = sorted_trends[:50]

    # Compute aggregate statistics
    platforms = Counter(item.get("_platform", "unknown") for item in analyzed)
    categories = Counter(item.get("category", "other") for item in analyzed)
    sentiments = Counter(item.get("sentiment", "neutral") for item in analyzed)
    lifecycles = Counter(item.get("lifecycle", "rising") for item in analyzed)

    scores = [item.get("relevance_score", 0) for item in analyzed if item.get("relevance_score")]
    avg_score = sum(scores) / len(scores) if scores else 0

    stats = {
        "total_items": len(analyzed),
        "by_platform": dict(platforms),
        "by_category": dict(categories),
        "by_sentiment": dict(sentiments),
        "by_lifecycle": dict(lifecycles),
        "avg_relevance_score": round(avg_score, 2),
        "score_range": {
            "min": round(min(scores), 2) if scores else 0,
            "max": round(max(scores), 2) if scores else 0,
        },
    }

    # Condense items for LLM (strip large fields)
    condensed_items = []
    for item in top_items:
        condensed_items.append({
            "title": item.get("title", "")[:300],
            "description": (item.get("description") or "")[:400],
            "platform": item.get("_platform", "unknown"),
            "category": item.get("category", "other"),
            "sentiment": item.get("sentiment", "neutral"),
            "lifecycle": item.get("lifecycle", "rising"),
            "relevance_score": item.get("relevance_score", 0),
            "related_topics": item.get("related_topics", []),
            "hashtags": item.get("hashtags", [])[:10],
            "views": item.get("views"),
            "likes": item.get("likes"),
            "comments_count": item.get("comments_count"),
            "shares": item.get("shares"),
            "author_name": item.get("author_name"),
            "source_url": item.get("source_url"),
        })

    return {
        "items": condensed_items,
        "stats": stats,
        "cross_platform_groups": cross_platform_groups,
        "all_trends_for_table": [
            {
                "title": item.get("title", "")[:200],
                "platform": item.get("_platform", "unknown"),
                "category": item.get("category", "other"),
                "relevance_score": item.get("relevance_score", 0),
                "sentiment": item.get("sentiment", "neutral"),
                "lifecycle": item.get("lifecycle", "rising"),
            }
            for item in sorted_trends
        ],
    }


async def _generate_report_markdown(report_data: dict) -> str:
    """Generate the full markdown report via LLM."""
    llm = get_report_llm()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    user_message = (
        f"Tạo báo cáo xu hướng cho ngày {today}.\n\n"
        f"## Thống Kê Tổng Hợp\n{json.dumps(report_data['stats'], indent=2)}\n\n"
        f"## Nhóm Đa Nền Tảng\n{json.dumps(report_data['cross_platform_groups'], indent=2, default=str)}\n\n"
        f"## Các Mục Xu Hướng Hàng Đầu (sắp xếp theo điểm liên quan)\n{json.dumps(report_data['items'], indent=2, default=str)}\n\n"
        f"## Tất Cả Xu Hướng Cho Bảng Xếp Hạng\n{json.dumps(report_data['all_trends_for_table'], indent=2, default=str)}"
    )

    response = await llm.ainvoke([
        SystemMessage(content=REPORT_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])

    return response.content


async def _generate_content_angles_json(top_items: list[dict]) -> list[dict]:
    """Generate structured content angle suggestions via a separate LLM call."""
    llm = get_report_llm()

    # Only send top 10 for content angles
    top_10 = top_items[:10]
    condensed = [
        {
            "title": item.get("title", ""),
            "platform": item.get("platform", "unknown"),
            "category": item.get("category", "other"),
            "sentiment": item.get("sentiment", "neutral"),
            "relevance_score": item.get("relevance_score", 0),
            "hashtags": item.get("hashtags", []),
        }
        for item in top_10
    ]

    response = await llm.ainvoke([
        SystemMessage(content=CONTENT_ANGLES_SYSTEM_PROMPT),
        HumanMessage(
            content=f"Generate content angles for these top 10 trending topics:\n\n{json.dumps(condensed, indent=2, default=str)}"
        ),
    ])

    content = response.content
    # Extract JSON from response
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    return json.loads(content.strip())


def _generate_fallback_report(report_data: dict) -> str:
    """Generate a basic template report when LLM fails."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = report_data["stats"]
    items = report_data["items"]
    all_trends = report_data["all_trends_for_table"]

    lines = [
        f"# Báo Cáo Xu Hướng Công Nghệ cho TikTok — {today}",
        "",
        "## Tóm Tắt Tổng Quan",
        "",
        f"Báo cáo này bao gồm **{stats['total_items']} mục xu hướng công nghệ** "
        f"từ Hacker News cho nội dung TikTok.",
        f"Điểm liên quan trung bình: **{stats['avg_relevance_score']}/10**.",
        "",
        "## Tổng Quan Thị Trường",
        "",
        "### Phân Bố Danh Mục",
    ]
    for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
        lines.append(f"- **{cat}**: {count} mục")

    lines.extend(["", "### Phân Bố Cảm Xúc"])
    for sent, count in sorted(stats["by_sentiment"].items(), key=lambda x: -x[1]):
        lines.append(f"- **{sent}**: {count} mục")

    lines.extend(["", "### Phân Bố Nền Tảng"])
    for plat, count in sorted(stats["by_platform"].items(), key=lambda x: -x[1]):
        lines.append(f"- **{plat}**: {count} mục")

    # Ranking table
    lines.extend([
        "",
        "## Bảng Xếp Hạng Xu Hướng",
        "",
        "| Hạng | Tiêu Đề | Nền Tảng | Danh Mục | Điểm | Cảm Xúc | Vòng Đời |",
        "|------|---------|----------|----------|------|---------|----------|",
    ])
    for i, item in enumerate(all_trends, 1):
        title = item["title"][:80]
        lines.append(
            f"| {i} | {title} | {item['platform']} | {item['category']} | "
            f"{item['relevance_score']} | {item['sentiment']} | {item['lifecycle']} |"
        )

    # Top 10 detailed
    lines.extend(["", "## Phân Tích Chi Tiết — Top 10 Xu Hướng", ""])
    for i, item in enumerate(items[:10], 1):
        views = item.get("views") or "N/A"
        likes = item.get("likes") or "N/A"
        comments = item.get("comments_count") or "N/A"
        shares = item.get("shares") or "N/A"
        hashtags = ", ".join(item.get("hashtags", [])) or "N/A"

        lines.extend([
            f"### {i}. {item['title']}",
            f"- **Nền tảng:** {item['platform']} | **Điểm:** {item['relevance_score']}/10 | **Vòng đời:** {item['lifecycle']}",
            f"- **Danh mục:** {item['category']} | **Cảm xúc:** {item['sentiment']}",
            f"- **Tương tác:** {views} lượt xem, {likes} lượt thích, {comments} bình luận, {shares} chia sẻ",
            f"- **Hashtags:** {hashtags}",
            "",
        ])

    # Cross-platform groups
    groups = report_data.get("cross_platform_groups", [])
    if groups:
        lines.extend(["## Xu Hướng Đa Nền Tảng", ""])
        for group in groups:
            lines.append(
                f"- **{group.get('representative_title', 'Unknown')}** — "
                f"Nền tảng: {', '.join(group.get('platforms', []))} | "
                f"Điểm tổng hợp: {group.get('combined_score', 0):.1f}"
            )

    lines.extend([
        "",
        "## Dữ Liệu Thô",
        "",
        "```json",
        json.dumps(
            {"stats": stats, "top_items": items[:10]},
            indent=2,
            default=str,
        ),
        "```",
        "",
        f"*Báo cáo được tạo lúc {datetime.now(timezone.utc).isoformat()} (bản mẫu dự phòng)*",
    ])

    return "\n".join(lines)


def _save_report_files(
    scan_run_id: str,
    report_markdown: str,
    summary_data: dict,
) -> str:
    """Save report.md and summary.json to disk. Returns the relative file path."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPORTS_DIR / scan_run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    # Save markdown report
    report_path = report_dir / f"{today}_report.md"
    report_path.write_text(report_markdown, encoding="utf-8")

    # Save structured summary JSON
    summary_path = report_dir / f"{today}_summary.json"
    summary_path.write_text(
        json.dumps(summary_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Return relative path from ai-service root
    relative_path = f"reports/{scan_run_id}/{today}_report.md"
    logger.info(
        "Report files saved",
        report_path=str(report_path),
        summary_path=str(summary_path),
    )
    return relative_path


async def reporter_node(state: TrendScanState) -> dict:
    """Generate a comprehensive trend report from analyzed data."""
    analyzed = state.get("analyzed_trends", [])
    scan_run_id = state.get("scan_run_id", "unknown")

    if not analyzed:
        logger.warning("Reporter: no analyzed trends to report")
        return {"report_content": "", "report_file_path": ""}

    logger.info("Reporter: starting report generation", total_items=len(analyzed))

    # Prepare data for LLM
    report_data = _prepare_report_data(state)

    # Generate markdown report via LLM
    try:
        report_markdown = await _generate_report_markdown(report_data)
        logger.info("Reporter: LLM report generated successfully")
    except Exception as e:
        logger.error("Reporter: LLM report generation failed, using fallback", error=str(e))
        report_markdown = _generate_fallback_report(report_data)

    # Generate structured content angles via separate LLM call
    content_angles = []
    try:
        content_angles = await _generate_content_angles_json(report_data["items"])
        logger.info("Reporter: content angles generated", count=len(content_angles))
    except Exception as e:
        logger.error("Reporter: content angles generation failed", error=str(e))

    # Build summary data for JSON file
    top_trends = [
        {
            "rank": i + 1,
            "title": item.get("title", ""),
            "platform": item.get("platform", "unknown"),
            "category": item.get("category", "other"),
            "relevance_score": item.get("relevance_score", 0),
            "sentiment": item.get("sentiment", "neutral"),
            "lifecycle": item.get("lifecycle", "rising"),
        }
        for i, item in enumerate(report_data["items"][:20])
    ]

    summary_data = {
        "scan_run_id": scan_run_id,
        "executive_summary": _extract_executive_summary(report_markdown),
        "total_trends": report_data["stats"]["total_items"],
        "platforms_covered": list(report_data["stats"]["by_platform"].keys()),
        "stats": report_data["stats"],
        "top_trends": top_trends,
        "content_angles": content_angles,
        "cross_platform_groups": report_data["cross_platform_groups"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Save files to disk
    report_file_path = _save_report_files(scan_run_id, report_markdown, summary_data)

    logger.info(
        "Reporter: completed",
        report_file_path=report_file_path,
        content_angles_count=len(content_angles),
    )

    return {
        "report_content": report_markdown,
        "report_file_path": report_file_path,
    }


def _extract_executive_summary(report_markdown: str) -> str:
    """Extract the Executive Summary section from the markdown report."""
    lines = report_markdown.split("\n")
    in_summary = False
    summary_lines = []

    for line in lines:
        if line.strip().startswith("## Tóm Tắt Tổng Quan") or line.strip().startswith("## Executive Summary"):
            in_summary = True
            continue
        if in_summary and line.strip().startswith("## "):
            break
        if in_summary:
            summary_lines.append(line)

    return "\n".join(summary_lines).strip()
