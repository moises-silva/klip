"""Web chat interface — unauthenticated, rate-limited, Google Search only."""

import asyncio
import logging
import pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from google.cloud import firestore
from google.genai import types as genai_types
from pydantic import BaseModel

from .auth import _get_db
from .config import settings
from .gemini import _get_client

logger = logging.getLogger(__name__)


def _require_web_enabled():
    if not settings.web_enabled:
        raise HTTPException(status_code=404)


router = APIRouter(dependencies=[Depends(_require_web_enabled)])

_RATE_LIMIT_COLLECTION = "web_rate_limits"
_STATIC = pathlib.Path(__file__).parent / "static"
_MAX_MESSAGE_CHARS = 2000


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _local_date(tz_name: str) -> str:
    """Return today's date string in the given IANA timezone, falling back to UTC."""
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz).date().isoformat()


async def _rate_limit_check(
    ip: str, fingerprint: str, tz_name: str
) -> tuple[bool, str]:
    """Check counters and increment if under limit. Returns (is_limited, error_message)."""
    db = _get_db()
    today = _local_date(tz_name)
    limit = settings.web_daily_limit
    ip_ref = db.collection(_RATE_LIMIT_COLLECTION).document(f"ip_{today}_{ip}")
    fp_ref = db.collection(_RATE_LIMIT_COLLECTION).document(f"fp_{today}_{fingerprint}")

    ip_doc, fp_doc = await asyncio.gather(ip_ref.get(), fp_ref.get())

    def count_for(doc) -> int:
        if doc.exists:
            d = doc.to_dict()
            return d.get("count", 0) if d.get("date") == today else 0
        return 0

    if count_for(ip_doc) >= limit:
        return True, "Daily message limit reached for your network. Try again tomorrow."
    if count_for(fp_doc) >= limit:
        return True, "Daily message limit reached. Try again tomorrow."

    async def increment(ref, doc):
        d = doc.to_dict() if doc.exists else {}
        if d.get("date") == today:
            await ref.update({"count": firestore.Increment(1)})
        else:
            await ref.set({"date": today, "count": 1})

    await asyncio.gather(increment(ip_ref, ip_doc), increment(fp_ref, fp_doc))
    return False, ""


def _system_prompt(custom_instruction: str = "", tz_name: str = "") -> str:
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    now = datetime.now(tz).strftime("%A, %B %d, %Y")
    text = (
        "You are Klip, a helpful AI assistant. "
        "Be concise and helpful. "
        f"Today is {now}. "
        "You have access to Google Search — use it to answer questions about "
        "current events, recent news, or anything requiring up-to-date information."
    )
    if custom_instruction:
        words = custom_instruction.split()
        truncated = " ".join(words[: settings.max_user_prompt_words])
        text += f"\n\nUser provided instructions:\n{truncated}"
    return text


_MAX_HISTORY_TURNS = 20
_MAX_HISTORY_ENTRY_CHARS = 10_000


def _build_contents(history: list[dict], message: str) -> list:
    """Convert history turns to Gemini Content objects and append the current message."""
    valid_roles = {"user", "model"}
    contents = []
    for turn in history[-_MAX_HISTORY_TURNS:]:
        role = turn.get("role", "")
        text = str(turn.get("text", ""))[:_MAX_HISTORY_ENTRY_CHARS]
        if role in valid_roles and text:
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part(text=text)])
            )
    contents.append(message)
    return contents


class ChatRequest(BaseModel):
    message: str
    custom_instruction: str = ""
    fingerprint: str = ""
    timezone: str = ""
    history: list[dict] = []


@router.get("/web", response_class=HTMLResponse)
async def web_index():
    return HTMLResponse((_STATIC / "index.html").read_text())


@router.post("/web/chat")
async def web_chat(request: Request, body: ChatRequest):
    message = body.message.strip()
    if not message:
        return JSONResponse({"error": "Message cannot be empty."}, status_code=400)
    if len(message) > _MAX_MESSAGE_CHARS:
        return JSONResponse(
            {"error": f"Message exceeds {_MAX_MESSAGE_CHARS} characters."},
            status_code=400,
        )

    ip = _client_ip(request)
    fingerprint = body.fingerprint or "unknown"
    tz_name = body.timezone

    limited, reason = await _rate_limit_check(ip, fingerprint, tz_name)
    if limited:
        return JSONResponse({"error": reason}, status_code=429)

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=_build_contents(body.history, message),
            config=genai_types.GenerateContentConfig(
                system_instruction=_system_prompt(body.custom_instruction, tz_name),
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )
        return JSONResponse({"reply": response.text or "(no response)"})
    except Exception as exc:
        logger.error("Web chat error ip=%s: %s", ip, exc, exc_info=True)
        return JSONResponse(
            {"error": "Something went wrong. Please try again."}, status_code=500
        )
