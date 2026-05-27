from functools import lru_cache

from firecrawl import V1FirecrawlApp

from app.config import get_settings


@lru_cache
def get_firecrawl() -> V1FirecrawlApp:
    settings = get_settings()
    return V1FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
