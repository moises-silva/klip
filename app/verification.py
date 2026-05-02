import logging

import google.auth.transport.requests
import google.oauth2.id_token

logger = logging.getLogger(__name__)

# Service account Google uses when calling Workspace Add-on HTTP endpoints.
GOOGLE_CHAT_ISSUER = "chat@system.gserviceaccount.com"

_transport_request = google.auth.transport.requests.Request()


def verify_addon_token(bearer_token: str, audience: str) -> bool:
    """
    Verify a Google-signed JWT sent by the Workspace Add-ons framework.

    Google signs each incoming request with a JWT whose issuer is the Chat
    service account and whose audience is the add-on's Cloud Run URL.
    """
    try:
        info = google.oauth2.id_token.verify_token(
            bearer_token,
            _transport_request,
            audience=audience,
        )
        issuer = info.get("email", "")
        if issuer != GOOGLE_CHAT_ISSUER:
            logger.warning("Unexpected token issuer: %s", issuer)
            return False
        return True
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        return False


def extract_bearer_token(authorization: str) -> str | None:
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return None
