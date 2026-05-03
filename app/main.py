import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .chat_events import (
    handle_added_to_space,
    handle_card_clicked,
    handle_message,
    handle_removed_from_space,
)
from .config import settings
from .verification import extract_bearer_token, verify_addon_token

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_EVENT_HANDLERS = {
    "ADDED_TO_SPACE": handle_added_to_space,
    "MESSAGE": handle_message,
    "CARD_CLICKED": handle_card_clicked,
    "REMOVED_FROM_SPACE": handle_removed_from_space,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Klip starting — model=%s verify_tokens=%s",
        settings.gemini_model,
        settings.verify_addon_tokens,
    )
    yield
    logger.info("Klip shutting down.")


app = FastAPI(title="Klip", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/events")
async def events(request: Request):
    if settings.verify_addon_tokens:
        auth_header = request.headers.get("Authorization", "")
        token = extract_bearer_token(auth_header)
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        if not verify_addon_token(token, settings.addon_audience, settings.addon_token_issuer):
            raise HTTPException(status_code=401, detail="Invalid token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = _detect_event_type(body)
    logger.info("Event received type=%s", event_type)

    handler = _EVENT_HANDLERS.get(event_type)
    if handler is None:
        logger.warning("Unhandled event type: %s | body: %s", event_type, body)
        return JSONResponse({})

    result = await handler(body)
    return JSONResponse(result)


def _detect_event_type(body: dict) -> str:
    """
    Workspace Add-ons events don't have a top-level 'type' field.
    The event type is inferred from which payload key is present in body['chat'].
    """
    chat = body.get("chat", {})
    if "messagePayload" in chat:
        return "MESSAGE"
    if "addedToSpacePayload" in chat:
        return "ADDED_TO_SPACE"
    if "removedFromSpacePayload" in chat:
        return "REMOVED_FROM_SPACE"
    if "buttonClickedPayload" in chat:
        return "CARD_CLICKED"
    return ""
