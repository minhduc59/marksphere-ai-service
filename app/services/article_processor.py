"""Crawl an article URL and turn it into a Stage-3-equivalent report.

The "express" pipeline (`/api/v1/posts/from-article`) calls these
functions to skip stages 1–3 of the regular trend pipeline.
"""
from __future__ import annotations

import asyncio

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.clients.firecrawl_client import get_firecrawl
from app.clients.openai_client import get_analyzer_llm
from app.services.article_schemas import ArticleReport

logger = structlog.get_logger()

PAYWALL_MIN_CHARS = 200


class ArticleFetchError(Exception):
    """Raised when Firecrawl cannot retrieve the article."""


class PaywallDetectedError(Exception):
    """Raised when the extracted body is too short to be usable."""


class ReportBuildError(Exception):
    """Raised when the LLM fails to produce a valid structured report."""


REPORT_SYSTEM_PROMPT = """You are a senior content strategist for a TikTok \
tech channel. You receive ONE article and must produce a single trend block \
in JSON that the downstream post-generator can consume.

Rules:
- Pick the strongest single topic from the article — do not split into multiple.
- `cleaned_content` should be a 800–2500 word markdown summary that preserves \
the article's core data points and arguments. It must read as standalone — \
the post-generator will only see this, not the original article.
- `tiktok_angles` must be 3 distinct, scroll-stopping hooks targeted at \
developers / tech-curious viewers. Each `format` must be one of: \
educational_breakdown, hot_take, tutorial, behind_the_scenes, trend_commentary.
- `key_data_points` should be concrete numbers, names, dates, or quotes \
extracted verbatim from the article.
- `target_audience` should be 1–4 entries from: developers, tech_enthusiasts, \
students, startup_founders.
- Sentiment / lifecycle / engagement_prediction must use the exact enum values."""


async def fetch_article(url: str) -> dict:
    """Fetch an article via Firecrawl. Returns dict with title, body, metadata.

    Raises ArticleFetchError on failure. The caller should treat any
    exception (including unexpected ones) as a fatal job error.
    """
    firecrawl = get_firecrawl()
    try:
        result = await asyncio.to_thread(
            firecrawl.scrape_url,
            url,
            formats=["markdown"],
        )
    except Exception as exc:
        raise ArticleFetchError(f"Firecrawl request failed: {exc}") from exc

    if result is None:
        raise ArticleFetchError("Firecrawl returned no result")

    body = (result.markdown or "").strip()
    metadata = result.metadata or {}
    title = (
        metadata.get("og:title")
        or metadata.get("title")
        or metadata.get("page_title")
        or "Untitled article"
    )

    if not body:
        raise ArticleFetchError("Firecrawl returned empty content")

    return {
        "url": url,
        "title": title,
        "body": body,
        "author": metadata.get("author"),
        "published_at": metadata.get("article:published_time"),
        "source_domain": metadata.get("og:site_name") or metadata.get("siteName"),
        "metadata": metadata,
    }


def detect_paywall(body: str) -> bool:
    return len(body.strip()) < PAYWALL_MIN_CHARS


async def build_article_report(article: dict) -> ArticleReport:
    """Call the analyzer LLM with structured output to build a report.

    Retries once on validation failure, then raises ReportBuildError.
    """
    llm = get_analyzer_llm().with_structured_output(ArticleReport)

    system = SystemMessage(content=REPORT_SYSTEM_PROMPT)
    user_content = (
        f"## Article URL\n{article['url']}\n\n"
        f"## Title\n{article['title']}\n\n"
        f"## Source\n{article.get('source_domain') or 'unknown'}\n\n"
        f"## Body\n{article['body']}"
    )

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            report = await llm.ainvoke([system, HumanMessage(content=user_content)])
            assert isinstance(report, ArticleReport)
            report.source_url = article["url"]
            return report
        except Exception as exc:
            last_error = exc
            logger.warning(
                "article_processor: report build failed",
                attempt=attempt,
                error=str(exc),
            )

    raise ReportBuildError(
        f"LLM failed to produce a valid report after 2 attempts: {last_error}"
    )
