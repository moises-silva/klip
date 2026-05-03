import logging

from .auth import get_auth_url, is_authorized, save_user_context
from .cards import text_response, welcome_card

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


async def handle_message(event: dict) -> dict:
    user_id = _user_id(event)
    text = _message_text(event)
    logger.info("MESSAGE user=%s text=%.100s", user_id, text)
    await _save_context(event)

    if not await is_authorized(user_id):
        auth_url = await get_auth_url(user_id)
        return welcome_card(auth_url)

    # TODO Phase 4: route to GeminiAgent.respond(text)
    return text_response("AI responses coming soon! (Phase 4)")


async def handle_card_clicked(event: dict) -> dict:
    action = _chat(event).get("buttonClickedPayload", {}).get("action", {}).get("actionMethodName", "")
    logger.info("CARD_CLICKED action=%s user=%s", action, _user_id(event))
    return {}


async def handle_removed_from_space(event: dict) -> dict:
    logger.info("REMOVED_FROM_SPACE user=%s", _user_id(event))
    return {}
