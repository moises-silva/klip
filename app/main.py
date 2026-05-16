import asyncio
import json
import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .chat_events import (
    handle_added_to_space,
    handle_app_command,
    handle_card_clicked,
    handle_message,
    handle_removed_from_space,
    replay_pending_message,
)
from .auth import handle_oauth_callback
from .config import settings
from .verification import extract_bearer_token, verify_addon_token

# Prevent BrokenPipeError noise when stdout is closed during shutdown (e.g. Ctrl+C).
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

if settings.debug_gemini:
    # Surfaces individual tool call counts and AFC decisions from the Gemini SDK.
    # Also enables DEBUG on the MCP transport layer for request/response tracing.
    logging.getLogger("google_genai.models").setLevel(logging.DEBUG)
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.DEBUG)
    logging.getLogger("app.gemini").setLevel(logging.DEBUG)

if settings.debug_mcp_http:
    # Log full HTTP request/response (headers + body) for every MCP call.
    logging.getLogger("app.mcp_client").setLevel(logging.DEBUG)

_EVENT_HANDLERS = {
    "ADDED_TO_SPACE": handle_added_to_space,
    "APP_COMMAND": handle_app_command,
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


@app.get("/auth/callback")
async def auth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    if error:
        logger.warning("OAuth denied: %s", error)
        return HTMLResponse(
            "<h2>Authorization denied</h2>"
            "<p>You can close this tab and try again from Google Chat.</p>"
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    try:
        redirect_uri, pending_replay = await handle_oauth_callback(code, state)
    except Exception as exc:
        logger.error("OAuth callback failed: %s", exc)
        raise HTTPException(status_code=400, detail="Authorization failed")

    if pending_replay:
        asyncio.create_task(replay_pending_message(**pending_replay))

    if redirect_uri:
        return RedirectResponse(url=redirect_uri)
    return HTMLResponse(
        "<h2>Authorization complete!</h2>"
        "<p>You can close this tab and return to Google Chat.</p>"
    )


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
        if not verify_addon_token(
            token, settings.addon_audience, settings.addon_token_issuer
        ):
            raise HTTPException(status_code=401, detail="Invalid token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = _detect_event_type(body)
    logger.info("Event received type=%s body=%s", event_type, json.dumps(body))

    handler = _EVENT_HANDLERS.get(event_type)
    if handler is None:
        logger.warning("Unhandled event type: %s | body: %s", event_type, body)
        return JSONResponse({})

    result = await handler(body)
    logger.info("Sending response: %s", json.dumps(result))
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
    if "appCommandPayload" in chat:
        return "APP_COMMAND"
    return ""
