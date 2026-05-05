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

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared._httpx_utils import create_mcp_http_client

logger = logging.getLogger(__name__)

CHAT_MCP_URL = "https://chatmcp.googleapis.com/mcp/v1"


async def _log_mcp_request(request: httpx.Request) -> None:
    logger.debug(
        "MCP HTTP request: %s %s\nHeaders: %s\nBody: %s",
        request.method,
        request.url,
        dict(request.headers),
        request.content.decode("utf-8", errors="replace") if request.content else "",
    )


async def _log_mcp_response(response: httpx.Response) -> None:
    try:
        await response.aread()
        logger.debug(
            "MCP HTTP response: %s\nHeaders: %s\nBody: %s",
            response.status_code,
            dict(response.headers),
            response.text,
        )
    except Exception as exc:
        logger.debug("MCP HTTP response: %s (could not read body: %s)", response.status_code, exc)


def _debug_http_client_factory(**kwargs) -> httpx.AsyncClient:
    client = create_mcp_http_client(**kwargs)
    client.event_hooks["request"].append(_log_mcp_request)
    client.event_hooks["response"].append(_log_mcp_response)
    return client


@asynccontextmanager
async def workspace_mcp_session(
    access_token: str | None = None,
    debug_http: bool = False,
) -> AsyncGenerator[ClientSession, None]:
    """Async context manager that yields an initialized MCP ClientSession."""
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    factory = _debug_http_client_factory if debug_http else create_mcp_http_client
    async with streamablehttp_client(CHAT_MCP_URL, headers=headers, httpx_client_factory=factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
