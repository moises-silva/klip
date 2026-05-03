"""
Gemini agentic loop with MCP tool dispatch.

The Gemini SDK natively supports passing an MCP ClientSession in the tools list.
It handles tool listing, function call dispatch, and the multi-turn loop
automatically via automatic function calling (AFC).
"""
import logging

import google.genai as genai
from google.genai import types as genai_types

from .config import settings
from .mcp_client import workspace_mcp_session

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You are Klip, a Google Workspace personal assistant. "
    "Help the user with their Google Chat conversations and Workspace data "
    "using the available tools. Be concise and helpful."
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


class GeminiAgent:
    """
    Orchestrates user message → Gemini (function calling) → MCP tool calls.
    Model is set by the operator via GEMINI_MODEL env var (default: gemini-2.0-flash).
    """

    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    async def respond(self, user_message: str) -> str:
        """Process a user message and return the assistant's response text."""
        client = _get_client()
        try:
            async with workspace_mcp_session(self.access_token) as session:
                response = await client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=user_message,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_SYSTEM_INSTRUCTION,
                        tools=[session],
                        automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                            disable=False,
                            maximum_remote_calls=10,
                        ),
                    ),
                )
                logger.info("Gemini response (with MCP) for user=%s", self.user_id)
        except Exception as exc:
            logger.warning(
                "MCP session failed for user=%s, falling back to no tools: %s",
                self.user_id,
                exc,
            )
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=user_message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION
                    + " Note: Workspace tools are temporarily unavailable.",
                ),
            )
            logger.info("Gemini response (no tools) for user=%s", self.user_id)

        return response.text or "(no response)"
