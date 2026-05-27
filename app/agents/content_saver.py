"""Save analyzed articles as individual markdown files.

Output location: reports/{scan_run_id}/articles/{slug}.md
- Development: local filesystem (ai-service/reports/...)
- Production: S3 bucket
"""

import re
from datetime import datetime, timezone

import structlog

from app.agents.state import TrendScanState
from app.core.storage import get_storage

logger = structlog.get_logger()


def _slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def _build_article_markdown(item: dict, index: int) -> str:
    """Build markdown for a single analyzed article with YAML frontmatter."""
    raw = item.get("raw_data", {})
    title = item.get("title", "Untitled")
    source_url = item.get("source_url", "")
    quality_score = item.get("quality_score", 0)
    sentiment = item.get("sentiment", "neutral")
    lifecycle = item.get("lifecycle", "rising")
    engagement = item.get("engagement_prediction", "medium")
    source_type = item.get("source_type", "community")
    category = item.get("category", "tech")
    hn_score = raw.get("hn_score", 0)
    hn_comments = raw.get("hn_comments", 0)
    hn_url = raw.get("hn_url", "")
    author = item.get("author_name", raw.get("hn_author", ""))
    published_at = item.get("published_at", "")
    cleaned_content = item.get("cleaned_content", "")
    key_data_points = item.get("key_data_points", [])
    target_audience = item.get("target_audience", [])
    content_angles = item.get("content_angles", [])

    lines = [
        "---",
        f'title: "{_escape_yaml(title)}"',
        f'source_url: "{source_url}"',
        f'source_type: "{source_type}"',
        f"quality_score: {quality_score}",
        f'sentiment: "{sentiment}"',
        f'lifecycle: "{lifecycle}"',
        f'engagement_prediction: "{engagement}"',
        f'category: "{category}"',
        f"hn_score: {hn_score}",
        f"hn_comments: {hn_comments}",
        f'hn_url: "{hn_url}"',
        f'author: "{_escape_yaml(author)}"',
        f'published_at: "{published_at}"',
        f"target_audience: {target_audience}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    # Key data points
    if key_data_points:
        lines.append("## Key Data Points")
        for dp in key_data_points:
            lines.append(f"- {dp}")
        lines.append("")

    # TikTok content angles
    if content_angles:
        lines.append("## TikTok Content Angles")
        for i, angle in enumerate(content_angles, 1):
            fmt = angle.get("format", "quick_tips")
            hook = angle.get("angle", "")
            hook_line = angle.get("hook_line", "")
            lines.append(f"### Angle {i}: {fmt}")
            lines.append(f"- **Hook:** {hook}")
            lines.append(f"- **Opening line:** \"{hook_line}\"")
            lines.append("")

    # Cleaned content
    if cleaned_content:
        lines.append("## Article Content")
        lines.append("")
        lines.append(cleaned_content)
        lines.append("")

    # Source links
    lines.append("---")
    if source_url:
        lines.append(f"[Original Article]({source_url})")
    if hn_url:
        lines.append(f" | [HN Discussion]({hn_url})")
    lines.append("")

    return "\n".join(lines)


def _escape_yaml(text: str) -> str:
    """Escape quotes in YAML string values."""
    return text.replace('"', '\\"').replace("\n", " ").strip()


async def content_saver_node(state: TrendScanState) -> dict:
    """Save analyzed articles as individual markdown files to reports/{scan_id}/articles/.

    Uses local filesystem in development, S3 in production.
    """
    analyzed = state.get("analyzed_trends", [])
    scan_run_id = state.get("scan_run_id", "unknown")

    if not analyzed:
        logger.info("ContentSaver: no analyzed articles to save")
        return {"content_file_paths": []}

    storage = get_storage()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    saved_paths = []

    for i, item in enumerate(analyzed):
        title = item.get("title", "untitled")
        slug = _slugify(title)
        key = f"reports/{scan_run_id}/articles/{date_str}_{slug}.md"

        try:
            markdown = _build_article_markdown(item, i)
            path = storage.write_text(key, markdown, content_type="text/markdown")
            saved_paths.append(path)
            logger.debug("ContentSaver: saved", file=key)
        except Exception as e:
            logger.warning("ContentSaver: failed to save", file=key, error=str(e))

    logger.info(
        "ContentSaver: completed",
        saved=len(saved_paths),
        total=len(analyzed),
        scan_run_id=scan_run_id,
    )
    return {"content_file_paths": saved_paths}
