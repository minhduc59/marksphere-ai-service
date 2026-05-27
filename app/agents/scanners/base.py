from abc import ABC, abstractmethod

import structlog

from app.agents.state import RawTrendData, TrendScanState
from app.core.rate_limiter import RateLimiter

logger = structlog.get_logger()


class BaseScannerNode(ABC):
    """Base class for all platform scanner nodes."""

    platform: str

    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter

    async def __call__(self, state: TrendScanState) -> dict:
        try:
            logger.info("Scanner starting", platform=self.platform)

            # Check rate limit
            await self.rate_limiter.check(self.platform)

            # Fetch fresh data
            items = await self.fetch(state.get("options", {}))

            # Log warning if no items returned
            if not items:
                logger.warning("Scanner returned 0 items", platform=self.platform)

            logger.info("Scanner completed", platform=self.platform, items=len(items))
            return {
                "raw_results": [
                    RawTrendData(
                        platform=self.platform,
                        items=items,
                        error=None,
                        metadata={"items_count": len(items)},
                    )
                ]
            }

        except Exception as e:
            logger.error("Scanner failed", platform=self.platform, error=str(e))
            return {
                "raw_results": [
                    RawTrendData(
                        platform=self.platform,
                        items=[],
                        error=str(e),
                        metadata={},
                    )
                ],
                "errors": [{"platform": self.platform, "error": str(e)}],
            }

    @abstractmethod
    async def fetch(self, options: dict) -> list[dict]:
        """Platform-specific data fetching. Must be implemented by subclasses."""
        ...
