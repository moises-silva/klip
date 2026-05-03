import logging

import google.auth.transport.requests
import google.oauth2.id_token

logger = logging.getLogger(__name__)

_transport_request = google.auth.transport.requests.Request()


def verify_addon_token(bearer_token: str, audience: str, expected_issuer: str) -> bool:
    """
    Verify a Google-signed JWT sent by the Workspace Add-ons framework.

    The issuer is the project-specific gsuiteaddons service account:
    service-{PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com
    """
    try:
        info = google.oauth2.id_token.verify_token(
            bearer_token,
            _transport_request,
            audience=audience,
        )
        issuer = info.get("email", "")
        if issuer != expected_issuer:
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
