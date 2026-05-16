"""OAuth 2.0 flow and Firestore token store."""
import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

import google.auth.transport.requests

import google.auth
from google.cloud import firestore
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .config import settings

logger = logging.getLogger(__name__)

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.memberships.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

_db: firestore.AsyncClient | None = None
_chat_service = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project=settings.gcp_project)
    return _db


def _get_chat_service():
    """Return a cached Chat API service client using the app's service account credentials."""
    global _chat_service
    if _chat_service is None:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/chat.bot"]
        )
        _chat_service = build("chat", "v1", credentials=credentials)
    return _chat_service


def _doc_id(user_id: str) -> str:
    """users/12345 → users_12345 (valid Firestore document ID)."""
    return user_id.replace("/", "_")


def _build_flow() -> Flow:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "redirect_uris": [f"{settings.app_base_url}/auth/callback"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=OAUTH_SCOPES,
    )
    flow.redirect_uri = f"{settings.app_base_url}/auth/callback"
    return flow


def _encode_state(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def _decode_state(state: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(state.encode()).decode())


async def delete_user(user_id: str) -> None:
    """Delete all stored data for a user (tokens, history, context, everything)."""
    db = _get_db()
    await db.collection("users").document(_doc_id(user_id)).delete()
    logger.info("Deleted all data for user=%s", user_id)


async def save_pending_message(user_id: str, text: str) -> None:
    """Persist the message that triggered a re-auth so it can be replayed after OAuth completes."""
    db = _get_db()
    await db.collection("users").document(_doc_id(user_id)).set(
        {"pending_message": text}, merge=True
    )
    logger.info("Saved pending message for user=%s", user_id)


async def save_user_context(
    user_id: str, space_name: str, config_redirect_uri: str, email: str = "", display_name: str = ""
) -> None:
    """Persist the user's DM space, email, display name, and configCompleteRedirectUri before OAuth."""
    db = _get_db()
    data = {"space_name": space_name, "config_redirect_uri": config_redirect_uri}
    if email:
        data["email"] = email
    if display_name:
        data["display_name"] = display_name
    await db.collection("users").document(_doc_id(user_id)).set(data, merge=True)
    logger.info("Saved context for user=%s space=%s email=%s", user_id, space_name, email)


async def get_user_info(user_id: str) -> dict:
    """Return stored email and display_name for a user."""
    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    if not doc.exists:
        return {}
    data = doc.to_dict()
    return {"email": data.get("email", ""), "display_name": data.get("display_name", "")}


async def get_user_settings(user_id: str) -> dict:
    """Return persisted user settings, or {} if none have been saved."""
    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    if not doc.exists:
        return {}
    return doc.to_dict().get("settings", {})


async def save_user_settings(user_id: str, data: dict) -> None:
    """Persist user settings (merged into the existing user document)."""
    db = _get_db()
    await db.collection("users").document(_doc_id(user_id)).set(
        {"settings": data}, merge=True
    )
    logger.info("Saved settings for user=%s", user_id)


async def get_auth_url(user_id: str) -> str:
    """Return the Google OAuth authorization URL for the given user."""
    if not settings.oauth_client_id or settings.oauth_client_id == "PLACEHOLDER":
        logger.warning("OAuth client ID not configured")
        return "#"
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=_encode_state({"user_id": user_id}),
        prompt="consent",
    )
    # Persist the PKCE code verifier (if the library generated one) so it can
    # be retrieved during the callback, which uses a fresh flow object.
    code_verifier = getattr(flow, "code_verifier", None) or getattr(
        getattr(flow, "oauth2session", None), "_code_verifier", None
    )
    if code_verifier:
        db = _get_db()
        await db.collection("users").document(_doc_id(user_id)).set(
            {"code_verifier": code_verifier}, merge=True
        )
    return auth_url


async def is_authorized(user_id: str) -> bool:
    """Return True if the user has a refresh token stored in Firestore."""
    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    if not doc.exists:
        return False
    return bool(doc.to_dict().get("refresh_token"))


async def store_tokens(user_id: str, credentials: Credentials) -> None:
    """Save OAuth tokens to the user's Firestore document."""
    db = _get_db()
    await db.collection("users").document(_doc_id(user_id)).set(
        {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=True,
    )


async def get_credentials(user_id: str) -> Credentials | None:
    """Return stored OAuth credentials for the user, or None if not authorized."""
    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    if not data.get("refresh_token"):
        return None
    expiry = None
    if data.get("token_expiry"):
        try:
            expiry = datetime.fromisoformat(data["token_expiry"])
        except ValueError:
            pass
    return Credentials(
        token=data.get("access_token"),
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.oauth_client_id,
        client_secret=settings.oauth_client_secret,
        expiry=expiry,
    )


async def get_fresh_access_token(user_id: str) -> str | None:
    """Return a valid access token, refreshing via the refresh token if expired."""
    creds = await get_credentials(user_id)
    if creds is None:
        return None
    if not creds.valid:
        try:
            request = google.auth.transport.requests.Request()
            await asyncio.to_thread(creds.refresh, request)
            await store_tokens(user_id, creds)
            logger.info("Refreshed access token for user=%s", user_id)
        except Exception as exc:
            logger.error("Token refresh failed for user=%s: %s", user_id, exc)
            return None
    return creds.token


async def _send_authorized_message(space_name: str) -> None:
    """Send a 'you're all set' message to the user's DM space using the app's credentials."""
    try:
        service = _get_chat_service()
        await asyncio.to_thread(
            service.spaces().messages().create(
                parent=space_name,
                body={"text": "You're all set! Go ahead and ask me anything."},
            ).execute
        )
        logger.info("Sent authorization complete message to space=%s", space_name)
    except Exception as exc:
        logger.error("Failed to send authorization complete message: %s", exc)


async def handle_oauth_callback(
    code: str, state: str
) -> tuple[str | None, dict | None]:
    """
    Exchange the authorization code for tokens, persist them, and return
    (configCompleteRedirectUri, pending_replay).

    pending_replay is a dict with user_id/space_name/text when the OAuth was
    triggered mid-conversation by a scope error — the caller should replay the
    original message instead of showing "You're all set!".
    """
    state_data = _decode_state(state)
    user_id = state_data["user_id"]

    # Retrieve the PKCE code verifier stored when the auth URL was generated
    db = _get_db()
    user_doc = await db.collection("users").document(_doc_id(user_id)).get()
    code_verifier = user_doc.to_dict().get("code_verifier") if user_doc.exists else None

    flow = _build_flow()
    fetch_kwargs = {"code": code}
    if code_verifier:
        fetch_kwargs["code_verifier"] = code_verifier
    # fetch_token makes a synchronous HTTP call — run in a thread
    await asyncio.to_thread(flow.fetch_token, **fetch_kwargs)
    await store_tokens(user_id, flow.credentials)
    logger.info("OAuth complete for user=%s", user_id)

    doc = await db.collection("users").document(_doc_id(user_id)).get()
    config_redirect_uri = None
    pending_replay = None
    if doc.exists:
        data = doc.to_dict()
        config_redirect_uri = data.get("config_redirect_uri")
        space_name = data.get("space_name")
        pending_message = data.get("pending_message")
        if pending_message and space_name:
            await db.collection("users").document(_doc_id(user_id)).set(
                {"pending_message": firestore.DELETE_FIELD}, merge=True
            )
            pending_replay = {"user_id": user_id, "space_name": space_name, "text": pending_message}
            logger.info("Pending message found for user=%s, will replay after re-auth", user_id)
        elif space_name:
            await _send_authorized_message(space_name)

    return config_redirect_uri, pending_replay
