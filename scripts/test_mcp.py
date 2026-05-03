#!/usr/bin/env python3
"""
Local MCP + Gemini integration test.

Runs four progressive levels, stopping at first failure.

Token input (tried in order):
  1. TEST_ACCESS_TOKEN env var  — paste directly from Firestore (~1h validity)
  2. TEST_REFRESH_TOKEN env var  — combined with OAUTH_CLIENT_ID + OAUTH_CLIENT_SECRET
                                   from .env; script refreshes automatically

Usage:
  # from the repo root
  export TEST_ACCESS_TOKEN="ya29...."
  python3 scripts/test_mcp.py

  # or with refresh token (reads client creds from .env)
  export TEST_REFRESH_TOKEN="1//..."
  python3 scripts/test_mcp.py

  # run only up to a specific level (1-4)
  python3 scripts/test_mcp.py --level 2
"""

import argparse
import asyncio
import logging
import os
import sys
import traceback

# Run from repo root so app.* imports work.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

# Enable verbose logging from all relevant libraries so errors are visible.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
# Quiet down noisy but uninteresting loggers.
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── helpers ──────────────────────────────────────────────────────────────────

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
HEAD = "\033[1m"
END  = "\033[0m"


def header(level: int, title: str) -> None:
    print(f"\n{HEAD}[Level {level}] {title}{END}")


def resolve_access_token() -> str:
    """Return a valid access token, refreshing if only a refresh token is given."""
    access_token = os.environ.get("TEST_ACCESS_TOKEN", "").strip()
    if access_token:
        print("Using TEST_ACCESS_TOKEN from environment.")
        return access_token

    refresh_token = os.environ.get("TEST_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        print(
            f"{FAIL}: Set TEST_ACCESS_TOKEN or TEST_REFRESH_TOKEN before running.",
            file=sys.stderr,
        )
        sys.exit(1)

    client_id     = os.environ.get("OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            f"{FAIL}: TEST_REFRESH_TOKEN requires OAUTH_CLIENT_ID and "
            "OAUTH_CLIENT_SECRET (loaded from .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Refreshing access token via TEST_REFRESH_TOKEN … ", end="", flush=True)
    from google.oauth2.credentials import Credentials
    import google.auth.transport.requests

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    creds.refresh(google.auth.transport.requests.Request())
    print("done.")
    print(f"  Access token: {creds.token[:20]}…")
    return creds.token


# ── test levels ───────────────────────────────────────────────────────────────

def _collect_leaves(exc: BaseException) -> list[BaseException]:
    """Unwrap nested ExceptionGroups and return the leaf exceptions."""
    if isinstance(exc, BaseExceptionGroup):
        leaves = []
        for sub in exc.exceptions:
            leaves.extend(_collect_leaves(sub))
        return leaves
    return [exc]


def _print_probe_error(url: str, exc: BaseException) -> None:
    leaves = _collect_leaves(exc)
    msgs = " | ".join(f"{type(e).__name__}: {e}" for e in leaves)
    print(f"  {url}  →  {msgs}")


async def _try_sse_handshake(url: str, access_token: str) -> bool:
    """Attempt an SSE MCP handshake. Returns True on success, False on failure."""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with sse_client(url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                print(f"  Server name:    {result.serverInfo.name}")
                print(f"  Server version: {result.serverInfo.version}")
                print(f"  Protocol:       {result.protocolVersion}")
                print(f"  Capabilities:   {result.capabilities}")
        return True
    except BaseException as exc:
        _print_probe_error(url, exc)
        return False


async def _try_streamable_handshake(url: str, access_token: str) -> bool:
    """Attempt a Streamable HTTP MCP handshake. Returns True on success, False on failure."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                print(f"  Server name:    {result.serverInfo.name}")
                print(f"  Server version: {result.serverInfo.version}")
                print(f"  Protocol:       {result.protocolVersion}")
                print(f"  Capabilities:   {result.capabilities}")
        return True
    except BaseException as exc:
        _print_probe_error(url, exc)
        return False


async def level0_raw_probe(access_token: str) -> None:
    """Send a raw tools/list JSON-RPC POST (mimicking the working curl) to candidate URLs."""
    import httpx

    header(0, "Raw HTTP probe (curl equivalent)")
    payload = {"method": "tools/list", "jsonrpc": "2.0", "id": 1}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    urls = [
        "https://chatmcp.googleapis.com/mcp/v1",
    ]
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        for url in urls:
            try:
                r = await client.post(url, json=payload, headers=headers)
                print(f"  {url}  →  HTTP {r.status_code}")
                print(f"    Content-Type: {r.headers.get('content-type', 'n/a')}")
                print(f"    Body preview: {r.text[:300]}")
            except Exception as exc:
                print(f"  {url}  →  {type(exc).__name__}: {exc}")


async def level1_handshake(access_token: str) -> None:
    """Try candidate URLs and transports until one completes the MCP handshake."""
    header(1, "MCP handshake")

    candidates = [
        ("streamable", "https://chatmcp.googleapis.com/mcp/v1"),
        ("sse",        "https://chatmcp.googleapis.com/mcp/v1"),
    ]

    for transport, url in candidates:
        print(f"  Trying [{transport}] {url} …")
        if transport == "sse":
            ok = await _try_sse_handshake(url, access_token)
        else:
            ok = await _try_streamable_handshake(url, access_token)
        if ok:
            print(f"\n  Working config: transport={transport}  url={url}")
            print(f"  Update CHAT_MCP_URL in app/mcp_client.py if different from current.")
            print(f"  {PASS}")
            return

    raise RuntimeError(
        "All candidate URLs/transports failed. See errors above for details."
    )


async def level2_list_tools(access_token: str) -> list:
    """List all tools exposed by the Chat MCP server (no auth needed for discovery)."""
    header(2, "Tool discovery")
    from app.mcp_client import workspace_mcp_session

    async with workspace_mcp_session() as session:
        result = await session.list_tools()
        tools = result.tools

    if not tools:
        print("  No tools returned — server connected but reported zero tools.")
    else:
        print(f"  {len(tools)} tool(s) available:")
        for t in tools:
            desc = (t.description or "").split("\n")[0][:80]
            print(f"    • {t.name}: {desc}")
    print(f"  {PASS}")
    return tools


async def level3_call_tool(access_token: str, tools: list) -> None:
    """Call the first available tool with empty args as a smoke-test."""
    header(3, "Single tool call")
    from app.mcp_client import workspace_mcp_session

    if not tools:
        print("  Skipped — no tools discovered in Level 2.")
        return

    # Prefer a tool with "list" or "get" in the name (read-only), else use first.
    target = next(
        (t for t in tools if any(kw in t.name.lower() for kw in ("list", "get", "search"))),
        tools[0],
    )
    print(f"  Calling tool: {target.name}")
    print(f"  Input schema: {target.inputSchema}")

    async with workspace_mcp_session(access_token) as session:
        result = await session.call_tool(target.name, arguments={})

    if result.isError:
        print(f"  Tool returned isError=True: {result.content}")
        print(f"  (This may be expected if the tool requires arguments.)")
    else:
        content_preview = str(result.content)[:300]
        print(f"  Result preview: {content_preview}")
    print(f"  {PASS}")


async def level4_gemini_loop(access_token: str) -> None:
    """Run a full GeminiAgent.respond() call end-to-end."""
    header(4, "Full Gemini + MCP loop")
    from app.gemini import GeminiAgent
    from app.config import settings

    if not settings.gemini_api_key or settings.gemini_api_key == "PLACEHOLDER":
        print(f"  Skipped — GEMINI_API_KEY not set in .env")
        return

    prompt = "List the Google Chat spaces I'm a member of."
    print(f"  Prompt: {prompt!r}")
    print(f"  Model:  {settings.gemini_model}")
    print("  Calling GeminiAgent.respond() …")

    agent = GeminiAgent(user_id="test-user", access_token=access_token)
    response = await agent.respond(prompt)

    print(f"\n  --- Gemini response ---")
    print(f"  {response}")
    print(f"  --- end ---\n")
    print(f"  {PASS}")


# ── main ──────────────────────────────────────────────────────────────────────

def _print_exc(exc: BaseException, indent: int = 0) -> None:
    """Print exception with full traceback, unwrapping ExceptionGroup recursively."""
    pad = "  " * indent
    if isinstance(exc, BaseExceptionGroup):
        print(f"{pad}ExceptionGroup ({len(exc.exceptions)} sub-exception(s)):", file=sys.stderr)
        for i, sub in enumerate(exc.exceptions, 1):
            print(f"{pad}  [{i}]", file=sys.stderr)
            _print_exc(sub, indent + 2)
    else:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        for line in tb.splitlines():
            print(f"{pad}{line}", file=sys.stderr)


async def main(max_level: int) -> None:
    access_token = resolve_access_token()

    tools: list = []
    try:
        if max_level >= 0:
            await level0_raw_probe(access_token)
        if max_level >= 1:
            await level1_handshake(access_token)
        if max_level >= 2:
            tools = await level2_list_tools(access_token)
        if max_level >= 3:
            await level3_call_tool(access_token, tools)
        if max_level >= 4:
            await level4_gemini_loop(access_token)
    except BaseException as exc:
        print(f"\n{FAIL}: {type(exc).__name__}: {exc}", file=sys.stderr)
        _print_exc(exc)
        sys.exit(1)

    print(f"\n{PASS} All levels up to {max_level} passed.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test MCP + Gemini locally.")
    parser.add_argument(
        "--level",
        type=int,
        default=4,
        choices=[0, 1, 2, 3, 4],
        help="Run tests up to this level (0=raw probe, 1=MCP handshake, …, default: 4).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.level))
