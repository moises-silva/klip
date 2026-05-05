"""Bot-initiated Chat REST API calls using the service account client from auth."""
import asyncio
import logging

from .auth import _get_chat_service

logger = logging.getLogger(__name__)


async def post_message(space_name: str, text: str) -> None:
    """Post a message to a Chat space as the bot."""
    service = _get_chat_service()
    await asyncio.to_thread(
        service.spaces().messages().create(
            parent=space_name,
            body={"text": text},
        ).execute
    )
    logger.info("Posted async reply to space=%s", space_name)
