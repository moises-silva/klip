"""
MCP host — connects to Google Workspace remote MCP servers over HTTP.

Architecture:
  Our app is an MCP *host*. It dispatches tool calls from Gemini to the
  appropriate remote MCP server using the user's delegated OAuth access token.

Transport: Streamable HTTP (POST-based). Confirmed working at
https://chatmcp.googleapis.com/mcp/v1. SSE (GET) returns 405.
"""
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

CHAT_MCP_URL = "https://chatmcp.googleapis.com/mcp/v1"


@asynccontextmanager
async def workspace_mcp_session(
    access_token: str | None = None,
) -> AsyncGenerator[ClientSession, None]:
    """Async context manager that yields an initialized MCP ClientSession."""
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    async with streamablehttp_client(CHAT_MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
