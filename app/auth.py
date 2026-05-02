"""OAuth 2.0 flow and Firestore token store — implemented in Phase 3."""
import logging

logger = logging.getLogger(__name__)


async def get_auth_url(user_id: str) -> str:
    """Return the OAuth authorization URL for the given user."""
    # TODO Phase 3: construct Google OAuth URL with required Chat + People scopes
    return "#"


async def is_authorized(user_id: str) -> bool:
    """Return True if the user has completed OAuth and tokens are stored."""
    # TODO Phase 3: check Firestore for a valid (non-expired) token doc
    return False
