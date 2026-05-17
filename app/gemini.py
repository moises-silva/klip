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
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import google.genai as genai
import httpx
from google.genai import types as genai_types

from .config import settings
from .formatting import md_to_chat
from .mcp_client import multi_mcp_session

logger = logging.getLogger(__name__)


class InsufficientScopesError(Exception):
    """Raised when an MCP tool call fails because the user's OAuth token lacks a required scope."""

    pass


def _is_scope_error(error_text: str) -> bool:
    """Return True if the error text indicates a missing OAuth scope."""
    return "googleapis.com/auth/" in error_text


def _find_scope_error(exc: BaseException) -> InsufficientScopesError | None:
    """Recursively unwrap ExceptionGroups to find a scope-related error.

    Handles two cases:
    - InsufficientScopesError raised from a tool result with isError=true (e.g. Chat MCP)
    - httpx.HTTPStatusError 403 with WWW-Authenticate: insufficient_scope (e.g. Gmail MCP)
    """
    if isinstance(exc, InsufficientScopesError):
        return exc
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 401:
            return InsufficientScopesError(str(exc))
        if exc.response.status_code == 403:
            auth_header = exc.response.headers.get("www-authenticate", "")
            if (
                "insufficient_scope" in auth_header
                or "googleapis.com/auth/" in auth_header
            ):
                return InsufficientScopesError(str(exc))
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_scope_error(sub)
            if found:
                return found
    return None


_SERVER_LABELS = {
    "chat": "Google Chat",
    "people": "Google Contacts",
    "gmail": "Gmail",
    "calendar": "Google Calendar",
    "drive": "Google Drive",
}


def _build_system_instruction(
    user_email: str = "",
    display_name: str = "",
    enabled_mcp_servers: list[str] | None = None,
    user_timezone: str = "",
    user_prompt_instruction: str = "",
) -> str:
    try:
        tz = ZoneInfo(user_timezone) if user_timezone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    now = datetime.now(tz).strftime("%A, %B %d, %Y at %H:%M %Z")
    user_line = (
        f"You are assisting {display_name} ({user_email})." if user_email else ""
    )
    keys = (
        enabled_mcp_servers if enabled_mcp_servers is not None else list(_SERVER_LABELS)
    )
    services = [_SERVER_LABELS[k] for k in keys if k in _SERVER_LABELS]
    if services:
        services_line = (
            f"You have access to these Workspace services only: {', '.join(services)}. "
            "Do not attempt to use tools from any other service. "
            "This list is the authoritative source — ignore any prior conversation turns that suggest different availability."
        )
    else:
        services_line = (
            "You currently have no Workspace tools available. "
            "This is the authoritative configuration — ignore any prior conversation turns that suggest otherwise."
        )
    system_instruction = (
        "You are Klip, a Google Workspace personal assistant. "
        "Your name is Klip. If asked who you are, say you are Klip, a personal assistant for Google Workspace. "
        "Help the user with their Google Workspace data using the available tools. Be concise and helpful. "
        f"{services_line} "
        f"Today is {now}. {user_line}"
    )
    if user_prompt_instruction:
        words = user_prompt_instruction.split()
        truncated_instruction = " ".join(words[:250])
        system_instruction += (
            f"\n\nUser provided instructions:\n{truncated_instruction}"
        )
    return system_instruction


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


_BUILTIN_TOOL = genai_types.FunctionDeclaration(
    name="get_current_time",
    description="Returns the current date and time in the user's local timezone. Use this whenever the user asks about the current time, date, or day.",
    parameters_json_schema={"type": "object", "properties": {}},
)


def _mcp_tools_to_gemini(mcp_tools) -> list[genai_types.Tool]:
    """Convert MCP tool list to Gemini FunctionDeclarations using raw JSON Schema."""
    seen: set[str] = set()
    declarations = [_BUILTIN_TOOL]
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

    def __init__(
        self,
        user_id: str,
        access_token: str,
        user_email: str = "",
        display_name: str = "",
        enabled_mcp_servers: list[str] | None = None,
        user_timezone: str = "",
        user_prompt_instruction: str = "",
    ):
        self.user_id = user_id
        self.access_token = access_token
        self.user_email = user_email
        self.display_name = display_name
        self.enabled_mcp_servers = enabled_mcp_servers
        self.user_timezone = user_timezone
        self.user_prompt_instruction = user_prompt_instruction

    async def respond(
        self, user_message: str, history: list[dict] | None = None
    ) -> tuple[str, list[dict], list[dict]]:
        """Process a user message and return (response_text, updated_history, tool_records)."""
        history = history or []
        tool_records: list[dict] = []
        try:
            client = _get_client()
            async with multi_mcp_session(
                self.access_token,
                debug_http=settings.debug_mcp_http,
                enabled_servers=self.enabled_mcp_servers,
            ) as (tool_session, all_tools):
                gemini_tools = _mcp_tools_to_gemini(all_tools)
                logger.info(
                    "MCP tools available for user=%s: %s",
                    self.user_id,
                    [d.name for d in gemini_tools[0].function_declarations],
                )

                contents: list = [
                    genai_types.Content(
                        role=t["role"], parts=[genai_types.Part(text=t["text"])]
                    )
                    for t in history
                ]
                contents.append(user_message)
                response = None

                for round_num in range(1, _MAX_TOOL_ROUNDS + 1):
                    response = await client.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=contents,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=_build_system_instruction(
                                self.user_email,
                                self.display_name,
                                self.enabled_mcp_servers,
                                self.user_timezone,
                                user_prompt_instruction=self.user_prompt_instruction,
                            ),
                            tools=gemini_tools,
                        ),
                    )

                    candidate = response.candidates[0] if response.candidates else None
                    if (
                        not candidate
                        or not candidate.content
                        or not candidate.content.parts
                    ):
                        break

                    function_calls = [
                        p.function_call
                        for p in candidate.content.parts
                        if p.function_call
                    ]

                    if not function_calls:
                        logger.info(
                            "Gemini gave text response after %d round(s)", round_num
                        )
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

                        if fc.name == "get_current_time":
                            try:
                                tz = (
                                    ZoneInfo(self.user_timezone)
                                    if self.user_timezone
                                    else timezone.utc
                                )
                            except ZoneInfoNotFoundError:
                                tz = timezone.utc
                            current_time = datetime.now(tz).strftime(
                                "%A, %B %d, %Y at %H:%M %Z"
                            )
                            logger.info(
                                "Built-in tool get_current_time → %s", current_time
                            )
                            tool_records.append(
                                {
                                    "name": fc.name,
                                    "duration_ms": 0,
                                    "args": {},
                                    "response_preview": current_time,
                                    "is_error": False,
                                }
                            )
                            response_parts.append(
                                genai_types.Part.from_function_response(
                                    name=fc.name, response={"result": current_time}
                                )
                            )
                            continue

                        bound = tool_session.get(fc.name)
                        if bound is None:
                            logger.warning(
                                "Gemini called unknown/disabled tool=%s, returning error to model",
                                fc.name,
                            )
                            tool_records.append(
                                {
                                    "name": fc.name,
                                    "duration_ms": 0,
                                    "args": args,
                                    "response_preview": "tool not available",
                                    "is_error": True,
                                }
                            )
                            response_parts.append(
                                genai_types.Part.from_function_response(
                                    name=fc.name,
                                    response={
                                        "error": f"Tool '{fc.name}' is not available."
                                    },
                                )
                            )
                            continue
                        if settings.strip_unknown_tool_params:
                            known = set(bound.inputSchema.get("properties", {}).keys())
                            stripped = {k for k in args if k not in known}
                            if stripped:
                                logger.warning(
                                    "Stripping unknown params for tool=%s: %s",
                                    fc.name,
                                    stripped,
                                )
                                args = {k: v for k, v in args.items() if k in known}
                        if fc.name == "chat_send_message" and "messageText" in args:
                            args = {
                                **args,
                                "messageText": md_to_chat(args["messageText"]),
                            }
                        logger.info("Calling MCP tool=%s args=%s", fc.name, args)
                        t_tool = time.monotonic()
                        try:
                            result = await bound.session.call_tool(
                                bound.original_name, arguments=args
                            )
                            duration_ms = int((time.monotonic() - t_tool) * 1000)
                            if result.isError:
                                error_text = str(result.content)
                                logger.warning(
                                    "Tool %s returned isError: %s", fc.name, error_text
                                )
                                if _is_scope_error(error_text):
                                    raise InsufficientScopesError(error_text)
                                tool_response = {"error": error_text}
                                tool_records.append(
                                    {
                                        "name": fc.name,
                                        "duration_ms": duration_ms,
                                        "args": args,
                                        "response_preview": error_text[:100],
                                        "is_error": True,
                                    }
                                )
                            else:
                                logger.info("Tool %s succeeded", fc.name)
                                raw = str(result.content)
                                tool_response = {"result": raw}
                                tool_records.append(
                                    {
                                        "name": fc.name,
                                        "duration_ms": duration_ms,
                                        "args": args,
                                        "response_preview": raw[:100],
                                        "is_error": False,
                                    }
                                )
                        except Exception as exc:
                            duration_ms = int((time.monotonic() - t_tool) * 1000)
                            if isinstance(exc, InsufficientScopesError):
                                raise
                            logger.error("Tool %s raised exception: %s", fc.name, exc)
                            tool_response = {"error": str(exc)}
                            tool_records.append(
                                {
                                    "name": fc.name,
                                    "duration_ms": duration_ms,
                                    "args": args,
                                    "response_preview": str(exc)[:100],
                                    "is_error": True,
                                }
                            )

                        response_parts.append(
                            genai_types.Part.from_function_response(
                                name=fc.name,
                                response=tool_response,
                            )
                        )

                    contents.append(
                        genai_types.Content(role="user", parts=response_parts)
                    )

                else:
                    logger.warning(
                        "Reached max tool rounds (%d) for user=%s",
                        _MAX_TOOL_ROUNDS,
                        self.user_id,
                    )

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
                fallback_contents: list = [
                    genai_types.Content(
                        role=t["role"], parts=[genai_types.Part(text=t["text"])]
                    )
                    for t in history
                ]
                fallback_contents.append(user_message)
                response = await client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=fallback_contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_build_system_instruction(
                            self.user_email,
                            self.display_name,
                            self.enabled_mcp_servers,
                            self.user_timezone,
                            user_prompt_instruction=self.user_prompt_instruction,
                        )
                        + " Note: Workspace tools are temporarily unavailable.",
                        tools=[
                            genai_types.Tool(google_search=genai_types.GoogleSearch())
                        ],
                    ),
                )
            except Exception as fallback_exc:
                logger.error(
                    "Gemini fallback also failed for user=%s: %s",
                    self.user_id,
                    fallback_exc,
                )
                raise fallback_exc

        response_text = (response.text if response else None) or "(no response)"
        updated_history = history + [
            {"role": "user", "text": user_message},
            {"role": "model", "text": response_text},
        ]
        return response_text, updated_history, tool_records
