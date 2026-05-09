"""
Gemini agentic loop with MCP tool dispatch.

Implements the loop manually (rather than using the SDK's built-in MCP/AFC
integration) so that:
  - MCP tool schemas are passed as raw JSON Schema via parameters_json_schema,
    preserving all fields without conversion loss.
  - Individual tool calls and their results are logged for debuggability.
  - Duplicate tools from the MCP server are deduplicated.
"""
import logging

import google.genai as genai
from google.genai import types as genai_types

from .config import settings
from .mcp_client import CHAT_MCP_URL, PEOPLE_MCP_URL, workspace_mcp_session

logger = logging.getLogger(__name__)


class InsufficientScopesError(Exception):
    """Raised when an MCP tool call fails because the user's OAuth token lacks a required scope."""
    pass


def _is_scope_error(error_text: str) -> bool:
    """Return True if the error text indicates a missing OAuth scope."""
    return "googleapis.com/auth/" in error_text


def _find_scope_error(exc: BaseException) -> InsufficientScopesError | None:
    """Recursively unwrap ExceptionGroups to find an InsufficientScopesError."""
    if isinstance(exc, InsufficientScopesError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_scope_error(sub)
            if found:
                return found
    return None


_SYSTEM_INSTRUCTION = (
    "You are Klip, a Google Workspace personal assistant. "
    "Your name is Klip. If asked who you are, say you are Klip, a personal assistant for Google Workspace. "
    "Help the user with their Google Chat conversations and Workspace data "
    "using the available tools. Be concise and helpful."
)

_MAX_TOOL_ROUNDS = 10

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.region,
        )
    return _client


def _mcp_tools_to_gemini(mcp_tools) -> list[genai_types.Tool]:
    """Convert MCP tool list to Gemini FunctionDeclarations using raw JSON Schema."""
    seen: set[str] = set()
    declarations = []
    for tool in mcp_tools:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        declarations.append(
            genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.inputSchema,
            )
        )
    return [genai_types.Tool(function_declarations=declarations)]


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
        try:
            client = _get_client()
            dbg = settings.debug_mcp_http
            async with workspace_mcp_session(self.access_token, url=CHAT_MCP_URL, debug_http=dbg) as chat_session:
                async with workspace_mcp_session(self.access_token, url=PEOPLE_MCP_URL, debug_http=dbg) as people_session:
                    chat_tools = (await chat_session.list_tools()).tools
                    people_tools = (await people_session.list_tools()).tools
                    all_tools = chat_tools + people_tools
                    tool_session: dict = {t.name: chat_session for t in chat_tools}
                    tool_session.update({t.name: people_session for t in people_tools})
                    gemini_tools = _mcp_tools_to_gemini(all_tools)
                    logger.info(
                        "MCP tools available for user=%s: %s",
                        self.user_id,
                        [d.name for d in gemini_tools[0].function_declarations],
                    )

                    contents: list = [user_message]
                    response = None

                    for round_num in range(1, _MAX_TOOL_ROUNDS + 1):
                        response = await client.aio.models.generate_content(
                            model=settings.gemini_model,
                            contents=contents,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=_SYSTEM_INSTRUCTION,
                                tools=gemini_tools,
                            ),
                        )

                        candidate = response.candidates[0] if response.candidates else None
                        if not candidate or not candidate.content or not candidate.content.parts:
                            break

                        function_calls = [
                            p.function_call
                            for p in candidate.content.parts
                            if p.function_call
                        ]

                        if not function_calls:
                            logger.info("Gemini gave text response after %d round(s)", round_num)
                            break

                        logger.info(
                            "Round %d: Gemini requested %d tool call(s): %s",
                            round_num,
                            len(function_calls),
                            [fc.name for fc in function_calls],
                        )

                        # Append model turn to history
                        contents.append(candidate.content)

                        # Dispatch each tool call to the session that owns it
                        response_parts = []
                        for fc in function_calls:
                            args = dict(fc.args) if fc.args else {}
                            logger.info("Calling MCP tool=%s args=%s", fc.name, args)
                            session = tool_session.get(fc.name, chat_session)
                            try:
                                result = await session.call_tool(fc.name, arguments=args)
                                if result.isError:
                                    error_text = str(result.content)
                                    logger.warning("Tool %s returned isError: %s", fc.name, error_text)
                                    if _is_scope_error(error_text):
                                        raise InsufficientScopesError(error_text)
                                    tool_response = {"error": error_text}
                                else:
                                    logger.info("Tool %s succeeded", fc.name)
                                    tool_response = {"result": str(result.content)}
                            except Exception as exc:
                                if isinstance(exc, InsufficientScopesError):
                                    raise
                                logger.error("Tool %s raised exception: %s", fc.name, exc)
                                tool_response = {"error": str(exc)}

                            response_parts.append(
                                genai_types.Part.from_function_response(
                                    name=fc.name,
                                    response=tool_response,
                                )
                            )

                        contents.append(genai_types.Content(role="user", parts=response_parts))

                    else:
                        logger.warning("Reached max tool rounds (%d) for user=%s", _MAX_TOOL_ROUNDS, self.user_id)

        except BaseException as exc:
            scope_error = _find_scope_error(exc)
            if scope_error:
                raise scope_error
            logger.warning(
                "MCP session failed for user=%s, falling back to no tools: %s",
                self.user_id,
                exc,
                exc_info=True,
            )
            try:
                response = await client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=user_message,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_SYSTEM_INSTRUCTION
                        + " Note: Workspace tools are temporarily unavailable.",
                    ),
                )
            except Exception as fallback_exc:
                logger.error("Gemini fallback also failed for user=%s: %s", self.user_id, fallback_exc)
                return "Sorry, I'm having trouble reaching the AI service right now. Please try again later."

        return (response.text if response else None) or "(no response)"
