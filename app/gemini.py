"""
Gemini agentic loop with MCP tool dispatch — implemented in Phase 4.

Flow per user turn:
  1. Build Gemini request with tool declarations from WorkspaceMcpClient.list_tools()
  2. Send user message; Gemini may respond with one or more function_call parts.
  3. For each function_call: dispatch via WorkspaceMcpClient.call_tool().
  4. Feed tool results back to Gemini.
  5. Repeat until Gemini returns a text response.
"""
import logging

logger = logging.getLogger(__name__)


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
        # TODO Phase 4: implement the agentic loop described in the module docstring
        raise NotImplementedError("Gemini agent not yet implemented (Phase 4)")
