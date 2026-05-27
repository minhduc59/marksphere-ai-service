import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import ApiError, RateLimitError, ScraperError


def with_retry(max_attempts: int = 3, min_wait: int = 1, max_wait: int = 30):
    """Retry decorator for platform API calls."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((ApiError, ScraperError, httpx.HTTPStatusError)),
        reraise=True,
    )


def with_rate_limit_retry(max_attempts: int = 2, min_wait: int = 10, max_wait: int = 60):
    """Retry decorator that also retries on rate limit errors with longer backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((
            ApiError, ScraperError, RateLimitError, httpx.HTTPStatusError,
        )),
        reraise=True,
    )
