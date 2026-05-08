import asyncio
import logging

from .auth import get_auth_url, get_fresh_access_token, is_authorized, save_user_context
from .cards import text_response, welcome_card
from .chat_api import post_message
from .config import settings
from .gemini import GeminiAgent, InsufficientScopesError

logger = logging.getLogger(__name__)


def _chat(event: dict) -> dict:
    return event.get("chat", {})

def _user_id(event: dict) -> str:
    return _chat(event).get("user", {}).get("name", "unknown")

def _user_email(event: dict) -> str:
    return _chat(event).get("user", {}).get("email", "")

def _message_text(event: dict) -> str:
    return _chat(event).get("messagePayload", {}).get("message", {}).get("text", "").strip()

def _space_name(event: dict) -> str:
    chat = _chat(event)
    space = (
        chat.get("messagePayload", {}).get("space")
        or chat.get("addedToSpacePayload", {}).get("space", {})
    )
    return space.get("name", "")

def _config_redirect_uri(event: dict) -> str:
    chat = _chat(event)
    return (
        chat.get("messagePayload", {}).get("configCompleteRedirectUri")
        or chat.get("addedToSpacePayload", {}).get("configCompleteRedirectUri", "")
    )


async def _save_context(event: dict) -> None:
    """Persist space name and configCompleteRedirectUri for use in the OAuth callback."""
    user_id = _user_id(event)
    space = _space_name(event)
    redirect_uri = _config_redirect_uri(event)
    email = _user_email(event)
    if space:
        await save_user_context(user_id, space, redirect_uri, email)


async def handle_added_to_space(event: dict) -> dict:
    user_id = _user_id(event)
    logger.info("ADDED_TO_SPACE user=%s", user_id)
    await _save_context(event)
    auth_url = await get_auth_url(user_id)
    return welcome_card(auth_url)


async def _run_and_reply(agent: GeminiAgent, text: str, space: str, user_id: str) -> None:
    try:
        async with asyncio.timeout(settings.gemini_timeout):
            result = await agent.respond(text)
    except InsufficientScopesError:
        logger.warning("Insufficient OAuth scopes for user=%s, prompting re-auth", user_id)
        auth_url = await get_auth_url(user_id)
        result = (
            "I need additional permissions to complete this request. "
            f"Please re-authorize me: <{auth_url}|Click here to re-authorize>"
        )
    except TimeoutError:
        logger.warning("Gemini timed out for user=%s after %ds", user_id, settings.gemini_timeout)
        result = "Sorry, that request took too long. Please try a simpler query."
    except Exception as exc:
        logger.error("Background task failed for user=%s: %s", user_id, exc, exc_info=True)
        result = "Sorry, something went wrong. Please try again."
    try:
        await post_message(space, result)
    except Exception as exc:
        logger.error("Failed to post async reply to space=%s: %s", space, exc)


async def handle_message(event: dict) -> dict:
    user_id = _user_id(event)
    text = _message_text(event)
    logger.info("MESSAGE user=%s text=%.100s", user_id, text)
    await _save_context(event)

    if not await is_authorized(user_id):
        auth_url = await get_auth_url(user_id)
        return welcome_card(auth_url)

    access_token = await get_fresh_access_token(user_id)
    if not access_token:
        auth_url = await get_auth_url(user_id)
        return welcome_card(auth_url)

    space = _space_name(event)
    agent = GeminiAgent(user_id, access_token)
    asyncio.create_task(_run_and_reply(agent, text, space, user_id))
    return text_response("On it...")


async def handle_card_clicked(event: dict) -> dict:
    action = _chat(event).get("buttonClickedPayload", {}).get("action", {}).get("actionMethodName", "")
    logger.info("CARD_CLICKED action=%s user=%s", action, _user_id(event))
    return {}


async def handle_removed_from_space(event: dict) -> dict:
    logger.info("REMOVED_FROM_SPACE user=%s", _user_id(event))
    return {}
