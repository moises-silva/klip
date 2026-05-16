"""Bot-initiated Chat REST API calls using ADC (service account / Cloud Run identity)."""

import asyncio
import logging

import google.auth
import google.auth.transport.requests
import httpx

logger = logging.getLogger(__name__)

_CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
_MESSAGES_BASE = "https://chat.googleapis.com/v1"


def _get_bot_token() -> str:
    creds, _ = google.auth.default(scopes=[_CHAT_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


async def create_message(
    space_name: str, body: dict, thread_name: str | None = None
) -> tuple[str, str]:
    """Create a message in a Chat space and return (message_name, thread_name).

    Pass thread_name to post as a reply in an existing thread.
    """
    token = await asyncio.to_thread(_get_bot_token)
    params = {}
    if thread_name:
        body = {**body, "thread": {"name": thread_name}}
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_MESSAGES_BASE}/{space_name}/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=body,
        )
    if resp.is_error:
        logger.error("create_message failed: %s %s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    return data["name"], data["thread"]["name"]


async def update_message(message_name: str, body: dict, update_mask: str) -> None:
    """Update an existing Chat message in place."""
    token = await asyncio.to_thread(_get_bot_token)
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_MESSAGES_BASE}/{message_name}",
            headers={"Authorization": f"Bearer {token}"},
            params={"updateMask": update_mask},
            json=body,
        )
    if resp.is_error:
        logger.error("update_message failed: %s %s", resp.status_code, resp.text)
    resp.raise_for_status()


async def post_message(space_name: str, text: str) -> None:
    """Post a plain text message to a Chat space as the bot."""
    await create_message(space_name, {"text": text})
    logger.info("Posted async reply to space=%s", space_name)
