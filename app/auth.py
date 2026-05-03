"""OAuth 2.0 flow and Firestore token store."""
import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

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
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/directory.readonly",
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


async def save_user_context(
    user_id: str, space_name: str, config_redirect_uri: str, email: str = ""
) -> None:
    """Persist the user's DM space, email, and configCompleteRedirectUri before OAuth."""
    db = _get_db()
    data = {"space_name": space_name, "config_redirect_uri": config_redirect_uri}
    if email:
        data["email"] = email
    await db.collection("users").document(_doc_id(user_id)).set(data, merge=True)
    logger.info("Saved context for user=%s space=%s email=%s", user_id, space_name, email)


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
    return Credentials(
        token=data.get("access_token"),
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.oauth_client_id,
        client_secret=settings.oauth_client_secret,
    )


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


async def handle_oauth_callback(code: str, state: str) -> str | None:
    """
    Exchange the authorization code for tokens, persist them, and return the
    configCompleteRedirectUri to send the user back to Chat (or None).
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

    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    config_redirect_uri = None
    if doc.exists:
        data = doc.to_dict()
        config_redirect_uri = data.get("config_redirect_uri")
        space_name = data.get("space_name")
        if space_name:
            await _send_authorized_message(space_name)

    return config_redirect_uri
