class ScannerError(Exception):
    """Base exception for scanner errors."""

    def __init__(self, platform: str, message: str):
        self.platform = platform
        self.message = message
        super().__init__(f"[{platform}] {message}")


class RateLimitError(ScannerError):
    """Raised when a platform rate limit is exceeded."""
    pass


class ApiError(ScannerError):
    """Raised when a platform API returns an error."""

    def __init__(self, platform: str, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(platform, message)


class ScraperError(ScannerError):
    """Raised when web scraping fails."""
    pass
