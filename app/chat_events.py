import logging

from .auth import get_auth_url, is_authorized
from .cards import text_response, welcome_card

logger = logging.getLogger(__name__)


def _user_id(event: dict) -> str:
    return event.get("user", {}).get("name", "unknown")


async def handle_added_to_space(event: dict) -> dict:
    user_id = _user_id(event)
    space_type = event.get("space", {}).get("type", "")
    logger.info("ADDED_TO_SPACE user=%s space_type=%s", user_id, space_type)
    auth_url = await get_auth_url(user_id)
    return welcome_card(auth_url)


async def handle_message(event: dict) -> dict:
    user_id = _user_id(event)
    text = event.get("message", {}).get("text", "").strip()
    logger.info("MESSAGE user=%s text=%.100s", user_id, text)

    if not await is_authorized(user_id):
        auth_url = await get_auth_url(user_id)
        return welcome_card(auth_url)

    # TODO Phase 4: route to GeminiAgent.respond(text)
    return text_response("AI responses coming soon! (Phase 4)")


async def handle_card_clicked(event: dict) -> dict:
    action = event.get("action", {}).get("actionMethodName", "")
    user_id = _user_id(event)
    logger.info("CARD_CLICKED action=%s user=%s", action, user_id)
    # TODO Phase 3: handle OAuth-related button actions
    return text_response("")


async def handle_removed_from_space(event: dict) -> dict:
    user_id = _user_id(event)
    logger.info("REMOVED_FROM_SPACE user=%s", user_id)
    return {}
