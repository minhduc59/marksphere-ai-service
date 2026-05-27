from functools import lru_cache

import httpx

from app.config import get_settings


@lru_cache
def get_rapidapi_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        headers={
            "x-rapidapi-key": settings.RAPIDAPI_KEY,
        },
        timeout=30.0,
    )
