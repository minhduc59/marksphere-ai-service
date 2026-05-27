"""Hacker News API wrapper using the public Firebase API.

Fetches top stories and their details, then crawls linked article URLs
for full content extraction.
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx
import structlog

from app.core.retry import with_retry

logger = structlog.get_logger()

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
MAX_CONCURRENT_FETCHES = 10
MAX_CONCURRENT_CRAWLS = 5
CRAWL_TIMEOUT = 15  # seconds per article crawl
MIN_CONTENT_WORDS = 100

# Technology-related keywords for filtering
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
    "crypto", "blockchain", "bitcoin", "ethereum",
    "saas", "paas", "infrastructure", "server", "serverless",
    "algorithm", "compiler", "interpreter", "virtual machine",
    "network", "tcp", "dns", "cdn", "protocol",
    "model", "training", "inference", "transformer", "diffusion",
    "anthropic", "openai", "google", "meta", "microsoft", "apple", "nvidia",
}

# Non-tech categories to filter out
NON_TECH_PATTERNS = [
    r"\bsports?\b", r"\bfootball\b", r"\bbasketball\b", r"\bsoccer\b",
    r"\belection\b", r"\bpolitical party\b", r"\bvoting\b",
    r"\bcelebrit(y|ies)\b", r"\bhollywood\b", r"\bmovie review\b",
    r"\brecipe\b", r"\bcooking\b", r"\bfashion\b",
]


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML to text converter."""

    def __init__(self):
        super().__init__()
        self._result: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "footer", "header", "aside"}
        self.og_image = ""
        self.og_title = ""
        self.og_description = ""
        self.article_published_time = ""
        self.canonical_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_dict = dict(attrs)
        if tag in self._skip_tags:
            self._skip = True

        # Extract meta tags
        if tag == "meta":
            prop = attrs_dict.get("property", "") or attrs_dict.get("name", "")
            content = attrs_dict.get("content", "")
            if prop == "og:image" and content:
                self.og_image = content
            elif prop == "og:title" and content:
                self.og_title = content
            elif prop in ("og:description", "description") and content and not self.og_description:
                self.og_description = content
            elif prop == "article:published_time" and content:
                self.article_published_time = content

        if tag == "link":
            if attrs_dict.get("rel") == "canonical" and attrs_dict.get("href"):
                self.canonical_url = attrs_dict["href"]

    def handle_endtag(self, tag: str):
        if tag in self._skip_tags:
            self._skip = False
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._result.append("\n")

    def handle_data(self, data: str):
        if not self._skip:
            self._result.append(data)

    def get_text(self) -> str:
        text = "".join(self._result)
        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()


def _is_tech_related(title: str, text: str) -> bool:
    """Check if an article is technology-related."""
    combined = f"{title} {text[:1000]}".lower()

    # Check for tech keywords
    for keyword in TECH_KEYWORDS:
        if keyword in combined:
            return True

    # Check for non-tech patterns (strong signals to exclude)
    non_tech_score = 0
    for pattern in NON_TECH_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            non_tech_score += 1

    # If multiple non-tech signals and no tech keywords, exclude
    return non_tech_score == 0


def _dedup_key(url: str) -> str:
    """Generate a dedup key from the canonical URL."""
    normalized = re.sub(r"[?#].*$", "", url.lower().strip().rstrip("/"))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class HackerNewsTool:
    """Wrapper around the Hacker News Firebase API with article crawling."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

    async def close(self):
        await self._client.aclose()

    @with_retry(max_attempts=3)
    async def _fetch_top_story_ids(self, limit: int = 30) -> list[int]:
        """Fetch top story IDs from HN."""
        resp = await self._client.get(f"{HN_API_BASE}/topstories.json")
        resp.raise_for_status()
        ids = resp.json()
        return ids[:limit]

    @with_retry(max_attempts=2)
    async def _fetch_story(self, story_id: int) -> dict | None:
        """Fetch a single story's details."""
        resp = await self._client.get(f"{HN_API_BASE}/item/{story_id}.json")
        resp.raise_for_status()
        data = resp.json()
        if not data or data.get("type") != "story" or not data.get("url"):
            return None
        return data

    async def _crawl_article(self, url: str) -> dict | None:
        """Crawl a URL and extract article content + metadata."""
        try:
            resp = await self._client.get(url, timeout=CRAWL_TIMEOUT)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            html = resp.text
            parser = _HTMLTextExtractor()
            parser.feed(html)
            text = parser.get_text()

            # Check minimum content threshold
            if len(text.split()) < MIN_CONTENT_WORDS:
                return None

            return {
                "full_text": text,
                "og_image": parser.og_image,
                "og_title": parser.og_title,
                "og_description": parser.og_description,
                "published_time": parser.article_published_time,
                "canonical_url": parser.canonical_url or url,
            }

        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
            logger.debug("HN: crawl failed", url=url, error=str(e))
            return None
        except Exception as e:
            logger.debug("HN: crawl error", url=url, error=str(e))
            return None

    async def fetch_all(self, max_stories: int = 30) -> list[dict]:
        """Fetch top HN stories, crawl articles, filter and return tech items.

        Returns items in the common trend item format, sorted by HN score descending.
        Max 15 qualifying stories returned.
        """
        # Step 1: Fetch top story IDs
        story_ids = await self._fetch_top_story_ids(limit=max_stories)
        logger.info("HN: fetched story IDs", count=len(story_ids))

        # Step 2: Fetch story details in parallel
        sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async def fetch_with_sem(sid: int):
            async with sem:
                return await self._fetch_story(sid)

        story_tasks = [fetch_with_sem(sid) for sid in story_ids]
        story_results = await asyncio.gather(*story_tasks, return_exceptions=True)

        stories = []
        for result in story_results:
            if isinstance(result, dict) and result is not None:
                stories.append(result)

        logger.info("HN: fetched story details", total=len(stories))

        # Sort by score descending before crawling
        stories.sort(key=lambda s: s.get("score", 0), reverse=True)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_stories = []
        for story in stories:
            key = _dedup_key(story["url"])
            if key not in seen_urls:
                seen_urls.add(key)
                unique_stories.append(story)
        stories = unique_stories

        # Step 3: Crawl article URLs in parallel
        crawl_sem = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

        async def crawl_with_sem(story: dict):
            async with crawl_sem:
                article = await self._crawl_article(story["url"])
                return story, article

        crawl_tasks = [crawl_with_sem(s) for s in stories]
        crawl_results = await asyncio.gather(*crawl_tasks, return_exceptions=True)

        # Step 4: Build items, filter, validate
        items = []
        failed_urls = []

        for result in crawl_results:
            if isinstance(result, Exception):
                continue
            story, article = result

            if article is None:
                failed_urls.append({
                    "url": story["url"],
                    "reason": "Crawl failed or insufficient content",
                })
                continue

            # Tech filter
            if not _is_tech_related(story.get("title", ""), article["full_text"]):
                continue

            # Build common item format
            hn_time = story.get("time")
            published_at = article.get("published_time") or (
                datetime.fromtimestamp(hn_time, tz=timezone.utc).isoformat() if hn_time else None
            )

            item = {
                "title": story.get("title", ""),
                "description": article.get("og_description", "")[:500],
                "content_body": article["full_text"],
                "source_url": article.get("canonical_url") or story["url"],
                "platform": "hackernews",
                "tags": [],
                "hashtags": [],
                "views": None,
                "likes": story.get("score"),
                "comments_count": story.get("descendants", 0),
                "shares": None,
                "trending_score": float(story.get("score", 0)),
                "thumbnail_url": article.get("og_image") or None,
                "video_url": None,
                "image_urls": [article["og_image"]] if article.get("og_image") else [],
                "author_name": story.get("by"),
                "author_url": f"https://news.ycombinator.com/user?id={story.get('by', '')}",
                "author_followers": None,
                "published_at": published_at,
                "raw_data": {
                    "hn_id": story.get("id"),
                    "hn_title": story.get("title", ""),
                    "hn_score": story.get("score", 0),
                    "hn_comments": story.get("descendants", 0),
                    "hn_author": story.get("by", ""),
                    "hn_url": f"https://news.ycombinator.com/item?id={story.get('id', '')}",
                    "hn_time": hn_time,
                    "article_title": article.get("og_title") or story.get("title", ""),
                    "article_image_url": article.get("og_image", ""),
                    "article_description": article.get("og_description", ""),
                    "canonical_url": article.get("canonical_url", ""),
                },
                "dedup_key": _dedup_key(story["url"]),
            }
            items.append(item)

        # Sort by HN score descending, limit to 15
        items.sort(key=lambda x: x.get("trending_score", 0), reverse=True)
        items = items[:15]

        logger.info(
            "HN: pipeline complete",
            total_fetched=len(stories),
            total_qualified=len(items),
            total_failed=len(failed_urls),
        )

        return items
