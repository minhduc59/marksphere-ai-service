from app.agents.scanners.base import BaseScannerNode
from app.tools.hackernews_tool import HackerNewsTool


class HackerNewsScannerNode(BaseScannerNode):
    platform = "hackernews"

    def __init__(self, rate_limiter):
        super().__init__(rate_limiter)
        self.tool = HackerNewsTool()

    async def fetch(self, options: dict) -> list[dict]:
        max_stories = options.get("max_items_per_platform", 30)
        items = await self.tool.fetch_all(max_stories=max_stories)
        # Cleanup httpx client
        await self.tool.close()
        return items
