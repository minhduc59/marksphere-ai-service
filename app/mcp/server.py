"""MCP Server for trending content crawling tools.

Exposes HackerNews trending data tools via the Model Context Protocol.
"""

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP(
    "TikTok Tech Trend Scanner",
    instructions="Tools for crawling trending technology content from HackerNews for TikTok",
)


if __name__ == "__main__":
    mcp.run(transport="stdio")
