import asyncio
import json
import logging
import random
import time

from .auth import (
    ALL_SERVER_KEYS,
    delete_user,
    get_auth_url,
    get_fresh_access_token,
    get_user_info,
    get_user_settings,
    is_authorized,
    save_pending_message,
    save_user_context,
    save_user_settings,
)
from .history import clear_history, load_history, save_history
from .cards import (
    THINKING_PHRASES,
    reauth_card,
    services_changed_card,
    settings_dialog,
    settings_dialog_ok,
    text_response,
    thinking_card,
    welcome_card,
)
from .chat_api import create_message, update_message
from .formatting import md_to_chat
from .config import settings
from .gemini import GeminiAgent, InsufficientScopesError

logger = logging.getLogger(__name__)


def _chat(event: dict) -> dict:
    return event.get("chat", {})


def _user_id(event: dict) -> str:
    return _chat(event).get("user", {}).get("name", "unknown")


def _user_email(event: dict) -> str:
    return _chat(event).get("user", {}).get("email", "")


def _display_name(event: dict) -> str:
    return _chat(event).get("user", {}).get("displayName", "")


def _user_timezone(event: dict) -> str:
    return event.get("commonEventObject", {}).get("timeZone", {}).get("id", "")


def _message_text(event: dict) -> str:
    return (
        _chat(event)
        .get("messagePayload", {})
        .get("message", {})
        .get("text", "")
        .strip()
    )


def _space_name(event: dict) -> str:
    chat = _chat(event)
    space = (
        chat.get("messagePayload", {}).get("space")
        or chat.get("addedToSpacePayload", {}).get("space")
        or chat.get("appCommandPayload", {}).get("space")
        or chat.get("buttonClickedPayload", {}).get("space", {})
    )
    return space.get("name", "")


def _config_redirect_uri(event: dict) -> str:
    chat = _chat(event)
    return (
        chat.get("messagePayload", {}).get("configCompleteRedirectUri")
        or chat.get("addedToSpacePayload", {}).get("configCompleteRedirectUri")
        or chat.get("appCommandPayload", {}).get("configCompleteRedirectUri", "")
    )


def _app_command_id(event: dict) -> int | None:
    meta = _chat(event).get("appCommandPayload", {}).get("appCommandMetadata", {})
    cmd_id = meta.get("appCommandId")
    return int(cmd_id) if cmd_id is not None else None


async def _save_context(event: dict) -> None:
    """Persist space name and configCompleteRedirectUri for use in the OAuth callback."""
    user_id = _user_id(event)
    space = _space_name(event)
    redirect_uri = _config_redirect_uri(event)
    email = _user_email(event)
    name = _display_name(event)
    timezone = _user_timezone(event)
    if space:
        await save_user_context(user_id, space, redirect_uri, email, name, timezone)


async def handle_added_to_space(event: dict) -> dict:
    user_id = _user_id(event)
    logger.info("ADDED_TO_SPACE user=%s", user_id)
    await _save_context(event)
    auth_url = await get_auth_url(user_id)
    return welcome_card(auth_url)


async def _phrase_updater(message_name: str, stop: asyncio.Event) -> None:
    """Cycle through witty phrases in the thinking card every 3 seconds until stopped."""
    phrases = random.sample(THINKING_PHRASES, len(THINKING_PHRASES))
    idx = 0
    while not stop.is_set():
        await asyncio.sleep(3)
        if stop.is_set():
            break
        idx = (idx + 1) % len(phrases)
        try:
            await update_message(message_name, thinking_card(phrases[idx]), "cardsV2")
        except Exception as exc:
            logger.warning("Failed to update thinking phrase: %s", exc)


async def _run_and_reply(
    agent: GeminiAgent,
    text: str,
    space: str,
    user_id: str,
    message_name: str | None,
    thread_name: str | None = None,
    user_debug: bool = False,
) -> None:
    t_start = time.monotonic()
    stop = asyncio.Event()
    updater_task = None
    if message_name:
        updater_task = asyncio.create_task(_phrase_updater(message_name, stop))

    history: list[dict] = []
    try:
        history = await load_history(user_id)
    except Exception as exc:
        logger.warning("Failed to load history for user=%s: %s", user_id, exc)

    raw_result: str | None = None
    result: str | dict | None = None
    updated_history: list[dict] | None = None
    tool_records: list[dict] = []
    gemini_ms: int = 0
    try:
        async with asyncio.timeout(settings.gemini_timeout):
            t_gemini = time.monotonic()
            result, updated_history, tool_records = await agent.respond(text, history)
            gemini_ms = int((time.monotonic() - t_gemini) * 1000)
            raw_result = result
    except InsufficientScopesError:
        logger.warning(
            "Insufficient OAuth scopes for user=%s, prompting re-auth", user_id
        )
        await save_pending_message(user_id, text)
        auth_url = await get_auth_url(
            user_id, enabled_servers=agent.enabled_mcp_servers
        )
        result = reauth_card(auth_url)
    except TimeoutError:
        logger.warning(
            "Gemini timed out for user=%s after %ds", user_id, settings.gemini_timeout
        )
        result = "Sorry, that request took too long. Please try a simpler query."
    except Exception as exc:
        logger.error(
            "Background task failed for user=%s: %s", user_id, exc, exc_info=True
        )
        result = "Sorry, something went wrong. Please try again."
    finally:
        stop.set()
        if updater_task:
            await updater_task

    if updated_history is not None:
        try:
            await save_history(user_id, updated_history)
        except Exception as exc:
            logger.warning("Failed to save history for user=%s: %s", user_id, exc)

    if not result:
        return

    body = (
        result
        if isinstance(result, dict)
        else {"text": md_to_chat(result), "cardsV2": []}
    )

    posted = False
    if message_name:
        try:
            await update_message(message_name, body, "text,cardsV2")
            posted = True
        except Exception as exc:
            logger.error("Failed to update thinking card in place: %s", exc)

    if not posted:
        try:
            await create_message(space, body)
            posted = True
        except Exception as exc:
            logger.error("Failed to post async reply to space=%s: %s", space, exc)

    if (
        settings.debug_chat
        and user_debug
        and posted
        and raw_result is not None
        and thread_name
    ):
        total_ms = int((time.monotonic() - t_start) * 1000)
        debug_data = {
            "timing": {"total_ms": total_ms, "gemini_ms": gemini_ms},
            "gemini_raw": raw_result,
            "chat_sent_raw": body.get("text", ""),
            "tools": tool_records,
        }
        debug_json = json.dumps(debug_data, indent=2, ensure_ascii=False)
        try:
            await create_message(
                space, {"text": f"```\n{debug_json}\n```"}, thread_name=thread_name
            )
        except Exception as exc:
            logger.error("Failed to post debug message: %s", exc)


_COMMAND_FORGET_HISTORY = 1
_COMMAND_RESET = 2
_COMMAND_SETTINGS = 3


async def handle_message(event: dict) -> dict:
    user_id = _user_id(event)
    text = _message_text(event)
    logger.info("MESSAGE user=%s text=%.100s", user_id, text)
    await _save_context(event)

    user_settings = await get_user_settings(user_id)
    enabled_servers = user_settings.get("enabled_mcp_servers")

    if not await is_authorized(user_id):
        auth_url = await get_auth_url(user_id, enabled_servers=enabled_servers)
        return welcome_card(auth_url)

    access_token = await get_fresh_access_token(user_id)
    if not access_token:
        auth_url = await get_auth_url(user_id, enabled_servers=enabled_servers)
        return welcome_card(auth_url)

    space = _space_name(event)
    agent = GeminiAgent(
        user_id,
        access_token,
        _user_email(event),
        _display_name(event),
        enabled_mcp_servers=enabled_servers,
        user_timezone=_user_timezone(event),
    )

    # Create the thinking card now so it appears immediately when the sync response
    # completes. The background task then updates it in place as Gemini works.
    message_name = None
    thread_name = None
    try:
        phrase = random.choice(THINKING_PHRASES)
        message_name, thread_name = await create_message(space, thinking_card(phrase))
    except Exception as exc:
        logger.error("Failed to create thinking card for user=%s: %s", user_id, exc)

    asyncio.create_task(
        _run_and_reply(
            agent,
            text,
            space,
            user_id,
            message_name,
            thread_name,
            user_debug=user_settings.get("debug_chat", False),
        )
    )
    return {}


async def handle_app_command(event: dict) -> dict:
    user_id = _user_id(event)
    cmd_id = _app_command_id(event)
    logger.info("APP_COMMAND id=%s user=%s", cmd_id, user_id)
    await _save_context(event)

    if cmd_id == _COMMAND_FORGET_HISTORY:
        await clear_history(user_id)
        return text_response("Done! I've forgotten our conversation history.")

    if cmd_id == _COMMAND_RESET:
        await delete_user(user_id)
        return text_response(
            "You have been forgotten. 🫧 It's like we never met. Say hello to start fresh!"
        )

    if cmd_id == _COMMAND_SETTINGS:
        user_settings = await get_user_settings(user_id)
        enabled = user_settings.get("enabled_mcp_servers")  # None = all enabled
        debug_enabled = user_settings.get("debug_chat", False)
        return settings_dialog(enabled, debug_enabled=debug_enabled)

    logger.warning("Unhandled app command id=%s", cmd_id)
    return {}


async def handle_card_clicked(event: dict) -> dict:
    payload = _chat(event).get("buttonClickedPayload", {})
    action = payload.get("action", {}).get("actionMethodName", "")
    is_dialog = payload.get("isDialogEvent", False)
    dialog_event_type = payload.get("dialogEventType", "")
    logger.info(
        "CARD_CLICKED action=%s user=%s is_dialog=%s dialog_event_type=%s",
        action,
        _user_id(event),
        is_dialog,
        dialog_event_type,
    )

    action_name = (
        event.get("commonEventObject", {}).get("parameters", {}).get("actionName", "")
    )
    if action_name == "save_settings":
        user_id = _user_id(event)
        form_inputs = event.get("commonEventObject", {}).get("formInputs", {})
        selected = (
            form_inputs.get("mcp_servers", {}).get("stringInputs", {}).get("value", [])
        )
        debug_chat = bool(
            form_inputs.get("debug_chat", {}).get("stringInputs", {}).get("value")
        )
        logger.info(
            "Dialog save_settings user=%s enabled_servers=%s debug_chat=%s",
            user_id,
            selected,
            debug_chat,
        )

        old_settings = await get_user_settings(user_id)
        old_enabled = old_settings.get("enabled_mcp_servers")  # None = all previously

        await save_user_settings(
            user_id, {"enabled_mcp_servers": selected, "debug_chat": debug_chat}
        )
        await clear_history(user_id)

        # Prompt re-authorization whenever the service selection changes.
        # Post if: services changed AND (user is already authorized OR user chose a
        # subset while not yet authorized, e.g. after a reset).
        selected_set = set(selected)
        old_set = ALL_SERVER_KEYS if old_enabled is None else set(old_enabled)
        space = _space_name(event)
        if selected_set != old_set and space:
            authorized = await is_authorized(user_id)
            if authorized or selected_set != ALL_SERVER_KEYS:
                auth_url = await get_auth_url(user_id, enabled_servers=selected)
                try:
                    await create_message(space, services_changed_card(auth_url))
                except Exception as exc:
                    logger.error("Failed to post services changed card: %s", exc)

        return settings_dialog_ok()

    return {}


async def handle_removed_from_space(event: dict) -> dict:
    user_id = _user_id(event)
    logger.info("REMOVED_FROM_SPACE user=%s", user_id)
    await delete_user(user_id)
    return {}


async def replay_pending_message(user_id: str, space_name: str, text: str) -> None:
    """Replay a message that was interrupted by a re-auth flow."""
    logger.info("Replaying pending message for user=%s", user_id)
    access_token = await get_fresh_access_token(user_id)
    if not access_token:
        logger.error(
            "Cannot replay message for user=%s: no access token after re-auth", user_id
        )
        return

    user_info = await get_user_info(user_id)
    user_settings = await get_user_settings(user_id)
    agent = GeminiAgent(
        user_id,
        access_token,
        user_info.get("email", ""),
        user_info.get("display_name", ""),
        enabled_mcp_servers=user_settings.get("enabled_mcp_servers"),
        user_timezone=user_info.get("timezone", ""),
    )

    message_name = None
    thread_name = None
    try:
        phrase = random.choice(THINKING_PHRASES)
        message_name, thread_name = await create_message(
            space_name, thinking_card(phrase)
        )
    except Exception as exc:
        logger.error(
            "Failed to create thinking card for replay user=%s: %s", user_id, exc
        )

    asyncio.create_task(
        _run_and_reply(
            agent,
            text,
            space_name,
            user_id,
            message_name,
            thread_name,
            user_debug=user_settings.get("debug_chat", False),
        )
    )
