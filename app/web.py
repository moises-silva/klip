"""Web chat interface — Google-authenticated or guest, rate-limited, Google Search only."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import pathlib
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from google.cloud import firestore
from google.genai import types as genai_types
from pydantic import BaseModel

from .auth import _get_db
from .config import settings
from .gemini import _get_client

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_WEB_SCOPES = "openid email profile"


def _require_web_enabled():
    if not settings.web_enabled:
        raise HTTPException(status_code=404)


router = APIRouter(dependencies=[Depends(_require_web_enabled)])

_RATE_LIMIT_COLLECTION = "web_rate_limits"
_STATIC = pathlib.Path(__file__).parent / "static"
_MAX_MESSAGE_CHARS = 2000


def _web_redirect_uri() -> str:
    if settings.web_redirect_uri:
        return settings.web_redirect_uri
    return f"{settings.app_base_url}/auth/web/callback"


def _session_user(request: Request) -> dict | None:
    return request.session.get("web_user")


def _is_allowed(request: Request) -> bool:
    """True if the user has either signed in or explicitly chosen guest mode."""
    return "web_user" in request.session or "web_guest" in request.session


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _local_date(tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz).date().isoformat()


async def _rate_limit_check(
    ip: str, fingerprint: str, tz_name: str, is_guest: bool
) -> tuple[bool, str]:
    db = _get_db()
    today = _local_date(tz_name)
    limit = (
        settings.web_guest_daily_limit if is_guest else settings.web_user_daily_limit
    )
    ip_ref = db.collection(_RATE_LIMIT_COLLECTION).document(f"ip_{today}_{ip}")
    fp_ref = db.collection(_RATE_LIMIT_COLLECTION).document(f"fp_{today}_{fingerprint}")

    ip_doc, fp_doc = await asyncio.gather(ip_ref.get(), fp_ref.get())

    def count_for(doc) -> int:
        if doc.exists:
            d = doc.to_dict()
            return d.get("count", 0) if d.get("date") == today else 0
        return 0

    def limit_msg(reason: str) -> str:
        if is_guest:
            return f"{reason} Sign in with Google for a higher limit."
        return f"{reason} Try again tomorrow."

    if count_for(ip_doc) >= limit:
        return True, limit_msg("Daily limit reached for your network.")
    if count_for(fp_doc) >= limit:
        return True, limit_msg("Daily message limit reached.")

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


# ── Auth routes ────────────────────────────────────────────────────────────────


@router.get("/login")
async def web_login_page(request: Request):
    html = (_STATIC / "login.html").read_text()
    html = html.replace("{{GUEST_LIMIT}}", str(settings.web_guest_daily_limit))
    html = html.replace("{{USER_LIMIT}}", str(settings.web_user_daily_limit))
    return HTMLResponse(html)


@router.get("/login/google")
async def web_login_google(request: Request):
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()

    request.session["web_cv"] = code_verifier
    request.session["web_state"] = state

    params = {
        "client_id": settings.oauth_client_id,
        "redirect_uri": _web_redirect_uri(),
        "response_type": "code",
        "scope": _WEB_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return RedirectResponse(url=_GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params))


@router.get("/guest")
async def web_guest(request: Request):
    request.session["web_guest"] = True
    return RedirectResponse(url="/", status_code=302)


@router.get("/auth/web/callback")
async def web_auth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error:
        return HTMLResponse(
            "<p>Login cancelled. <a href='/login'>Try again</a>.</p>", status_code=400
        )

    stored_state = request.session.pop("web_state", None)
    code_verifier = request.session.pop("web_cv", None)

    if not code or not state or state != stored_state or not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.oauth_client_id,
                    "client_secret": settings.oauth_client_secret,
                    "redirect_uri": _web_redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as exc:
        logger.error("Web OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Login failed. Please try again.")

    email = userinfo.get("email", "")
    allowed = settings.web_allowed_emails
    if allowed and email not in allowed:
        logger.warning("Web login denied for %s", email)
        raise HTTPException(status_code=403, detail=f"Access denied for {email}.")

    request.session.pop("web_guest", None)
    request.session["web_user"] = {"email": email, "name": userinfo.get("name", "")}
    logger.info("Web login: %s", email)
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def web_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


# ── App routes ─────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
@router.get("/web", response_class=HTMLResponse)
async def web_index(request: Request):
    if not _is_allowed(request):
        return RedirectResponse(url="/login", status_code=302)

    user_data = _session_user(request)
    klip_user = {
        "guest": user_data is None,
        "email": user_data.get("email", "") if user_data else "",
        "name": user_data.get("name", "") if user_data else "",
        "daily_limit": (
            settings.web_guest_daily_limit
            if user_data is None
            else settings.web_user_daily_limit
        ),
    }
    html = (_STATIC / "index.html").read_text()
    html = html.replace(
        "</head>",
        f"<script>window.KLIP_USER={json.dumps(klip_user)};</script></head>",
        1,
    )
    return HTMLResponse(html)


@router.post("/web/chat")
async def web_chat(request: Request, body: ChatRequest):
    if not _is_allowed(request):
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

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
    is_guest = _session_user(request) is None

    limited, reason = await _rate_limit_check(ip, fingerprint, tz_name, is_guest)
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
