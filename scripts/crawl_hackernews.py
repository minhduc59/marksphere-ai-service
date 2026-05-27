#!/usr/bin/env python3
"""
Hacker News Technology News Crawler

Fetches top stories from HN, crawls full article content,
filters for technology topics, and saves as markdown files.

Usage:
    python scripts/crawl_hackernews.py [--max-stories 30] [--output-dir ./content]
"""

import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from firecrawl import V1V1FirecrawlApp

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
MAX_CONCURRENT_FETCHES = 10
MAX_CONCURRENT_CRAWLS = 5
CRAWL_TIMEOUT = 15
MIN_CONTENT_WORDS = 100
MAX_QUALIFYING = 15

TECH_KEYWORDS = {
    "ai", "ml", "llm", "gpt", "machine learning", "deep learning", "neural",
    "software", "programming", "developer", "engineering", "code", "coding",
    "python", "javascript", "typescript", "rust", "golang", "java", "c++",
    "api", "sdk", "framework", "library", "open source", "opensource", "github",
    "cloud", "aws", "gcp", "azure", "kubernetes", "docker", "devops",
    "database", "sql", "nosql", "postgres", "redis", "mongodb",
    "security", "cybersecurity", "privacy", "encryption", "vulnerability",
    "startup", "yc", "y combinator", "tech", "silicon valley",
    "hardware", "chip", "semiconductor", "gpu", "cpu", "arm", "risc",
    "data", "analytics", "data science", "pipeline",
    "robot", "robotics", "automation",
    "linux", "unix", "windows", "macos", "ios", "android",
    "web", "browser", "http", "frontend", "backend", "fullstack",
    "saas", "infrastructure", "server", "serverless",
    "algorithm", "compiler", "interpreter", "virtual machine",
    "network", "tcp", "dns", "cdn", "protocol",
    "model", "training", "inference", "transformer", "diffusion",
    "anthropic", "openai", "google", "meta", "microsoft", "apple", "nvidia",
    "computer", "science", "computing", "digital", "internet", "app",
    "deploy", "ci/cd", "testing", "debug", "performance", "optimization",
    "memory", "storage", "processor", "architecture", "system",
    "hacker", "exploit", "malware", "phishing", "firewall",
}

NON_TECH_PATTERNS = [
    r"\bsports?\b", r"\bfootball\b", r"\bbasketball\b", r"\bsoccer\b",
    r"\belection\b", r"\bpolitical party\b", r"\bvoting\b",
    r"\bcelebrit(y|ies)\b", r"\bhollywood\b", r"\bmovie review\b",
    r"\brecipe\b", r"\bcooking\b", r"\bfashion\b",
]


def _init_firecrawl() -> V1FirecrawlApp:
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        print("WARNING: FIRECRAWL_API_KEY not set. Firecrawl calls will fail.", file=sys.stderr)
    return V1FirecrawlApp(api_key=api_key)


def is_tech_related(title: str, text: str) -> bool:
    combined = f"{title} {text[:2000]}".lower()
    for keyword in TECH_KEYWORDS:
        if keyword in combined:
            return True
    non_tech_score = sum(1 for p in NON_TECH_PATTERNS if re.search(p, combined, re.IGNORECASE))
    return non_tech_score == 0


def dedup_key(url: str) -> str:
    normalized = re.sub(r"[?#].*$", "", url.lower().strip().rstrip("/"))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def slugify(text: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def escape_yaml(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", " ").strip()


def build_markdown(story: dict, article: dict, crawl_date: str) -> str:
    hn_title = story.get("title", "")
    hn_score = story.get("score", 0)
    hn_comments = story.get("descendants", 0)
    hn_author = story.get("by", "")
    hn_id = story.get("id", "")
    hn_url = f"https://news.ycombinator.com/item?id={hn_id}"

    article_title = article.get("og_title") or article.get("page_title") or hn_title
    article_description = article.get("og_description", "")
    article_url = article.get("canonical_url") or story.get("url", "")
    article_image_url = article.get("og_image", "")
    publication_date = article.get("published_time", "")
    full_text = article.get("full_text", "")

    if not publication_date and story.get("time"):
        publication_date = datetime.fromtimestamp(story["time"], tz=timezone.utc).strftime("%Y-%m-%d")

    lines = [
        "---",
        f'hn_title: "{escape_yaml(hn_title)}"',
        f"hn_score: {hn_score}",
        f"hn_comments: {hn_comments}",
        f'hn_author: "{hn_author}"',
        f'hn_url: "{hn_url}"',
        f'article_title: "{escape_yaml(article_title)}"',
        f'article_description: "{escape_yaml(article_description[:300])}"',
        f'article_url: "{article_url}"',
        f'article_image_url: "{article_image_url}"',
        f'publication_date: "{publication_date}"',
        f'crawl_date: "{crawl_date}"',
        f'crawl_status: "success"',
        "---",
        "",
        f"# {article_title}",
        "",
    ]

    if article_image_url:
        lines.extend([f"![Hero Image]({article_image_url})", ""])

    if full_text:
        lines.extend([full_text, ""])

    return "\n".join(lines)


async def fetch_top_story_ids(client: httpx.AsyncClient, limit: int = 30) -> list[int]:
    resp = await client.get(f"{HN_API_BASE}/topstories.json")
    resp.raise_for_status()
    return resp.json()[:limit]


async def fetch_story(client: httpx.AsyncClient, story_id: int) -> dict | None:
    try:
        resp = await client.get(f"{HN_API_BASE}/item/{story_id}.json")
        resp.raise_for_status()
        data = resp.json()
        if not data or data.get("type") != "story" or not data.get("url"):
            return None
        return data
    except Exception:
        return None


async def crawl_article(firecrawl: V1FirecrawlApp, url: str) -> dict | None:
    try:
        result = await asyncio.to_thread(
            firecrawl.scrape_url,
            url,
            formats=["markdown"],
        )

        markdown = (result.markdown or "") if result else ""
        if len(markdown.split()) < MIN_CONTENT_WORDS:
            return None

        metadata = (result.metadata or {}) if result else {}
        return {
            "full_text": markdown,
            "og_image": metadata.get("og:image", ""),
            "og_title": metadata.get("og:title", ""),
            "og_description": metadata.get("og:description", "") or metadata.get("description", ""),
            "published_time": metadata.get("article:published_time", ""),
            "canonical_url": metadata.get("og:url", "") or metadata.get("sourceURL", url),
            "page_title": metadata.get("title", ""),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


async def run_crawl(max_stories: int = 30, output_dir: str = "./content"):
    now = datetime.now(timezone.utc)
    crawl_date = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    date_str = now.strftime("%Y-%m-%d")

    output_path = Path(output_dir) / "hackernews" / date_str
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] Fetching top {max_stories} story IDs from Hacker News...")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )

    try:
        # Step 1: Fetch story IDs
        story_ids = await fetch_top_story_ids(client, limit=max_stories)
        print(f"       Got {len(story_ids)} story IDs")

        # Step 2: Fetch story details
        print("[2/5] Fetching story details...")
        sem_fetch = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async def fetch_with_sem(sid):
            async with sem_fetch:
                return await fetch_story(client, sid)

        story_results = await asyncio.gather(*[fetch_with_sem(sid) for sid in story_ids])
        stories = [s for s in story_results if s is not None]
        stories.sort(key=lambda s: s.get("score", 0), reverse=True)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_stories = []
        for story in stories:
            key = dedup_key(story["url"])
            if key not in seen_urls:
                seen_urls.add(key)
                unique_stories.append(story)
        stories = unique_stories
        print(f"       {len(stories)} unique stories with external URLs")

        # Step 3: Crawl articles via Firecrawl
        print(f"[3/5] Crawling {len(stories)} article URLs via Firecrawl...")
        firecrawl = _init_firecrawl()
        sem_crawl = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

        async def crawl_with_sem(story):
            async with sem_crawl:
                result = await crawl_article(firecrawl, story["url"])
                return story, result

        crawl_results = await asyncio.gather(*[crawl_with_sem(s) for s in stories])

        # Step 4: Validate & filter
        print("[4/5] Validating and filtering...")
        qualified = []
        failed_urls = []

        for story, article in crawl_results:
            if article is None:
                failed_urls.append({"url": story["url"], "reason": "Empty content or non-HTML"})
                continue
            if "error" in article:
                failed_urls.append({"url": story["url"], "reason": article["error"]})
                continue
            if not is_tech_related(story.get("title", ""), article["full_text"]):
                continue
            qualified.append((story, article))

        # Sort by score and limit
        qualified.sort(key=lambda x: x[0].get("score", 0), reverse=True)
        qualified = qualified[:MAX_QUALIFYING]

        print(f"       {len(qualified)} articles qualified (filtered from {len(stories)})")
        print(f"       {len(failed_urls)} URLs failed to crawl")

        # Step 5: Save markdown files
        print("[5/5] Saving markdown files...")
        saved_articles = []

        for story, article in qualified:
            article_title = article.get("og_title") or article.get("page_title") or story.get("title", "untitled")
            slug = slugify(article_title)
            filename = f"{date_str}_{slug}.md"
            filepath = output_path / filename

            md_content = build_markdown(story, article, crawl_date)
            filepath.write_text(md_content, encoding="utf-8")

            saved_articles.append({
                "hn_title": story.get("title", ""),
                "hn_score": story.get("score", 0),
                "article_url": article.get("canonical_url") or story["url"],
                "file_name": filename,
                "crawl_status": "success",
            })
            print(f"       Saved: {filename} (score: {story.get('score', 0)})")

        # Build summary
        summary = {
            "crawl_date": crawl_date,
            "environment": "local",
            "storage_path": str(output_path),
            "total_fetched": len(stories),
            "total_qualified": len(qualified),
            "total_failed": len(failed_urls),
            "articles": saved_articles,
            "failed_urls": failed_urls[:20],  # limit failed list
        }

        # Save summary JSON
        summary_path = output_path / f"{date_str}_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n       Summary saved: {summary_path}")

        if len(qualified) < 5:
            print(f"\n  WARNING: Only {len(qualified)} stories qualified. Consider broadening the technology keyword filter.")

        return summary

    finally:
        await client.aclose()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Crawl Hacker News for tech stories")
    parser.add_argument("--max-stories", type=int, default=30, help="Max stories to fetch from HN")
    parser.add_argument("--output-dir", type=str, default="./content", help="Output directory")
    args = parser.parse_args()

    summary = asyncio.run(run_crawl(max_stories=args.max_stories, output_dir=args.output_dir))
    print("\n" + "=" * 60)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
