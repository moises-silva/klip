"""Firestore-backed per-user conversation history."""

import logging
from datetime import datetime, timezone

from google.cloud import firestore

from .config import settings

logger = logging.getLogger(__name__)

MAX_TURNS = 20

_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project=settings.gcp_project)
    return _db


def _doc_id(user_id: str) -> str:
    return user_id.replace("/", "_")


async def load_history(user_id: str) -> list[dict]:
    """Return stored conversation turns, oldest first. Empty list if none."""
    db = _get_db()
    doc = await db.collection("users").document(_doc_id(user_id)).get()
    if not doc.exists:
        return []
    return doc.to_dict().get("conversation", [])


async def save_history(user_id: str, turns: list[dict]) -> None:
    """Persist conversation turns, capped to MAX_TURNS."""
    if len(turns) > MAX_TURNS:
        turns = turns[-MAX_TURNS:]
    db = _get_db()
    await (
        db.collection("users")
        .document(_doc_id(user_id))
        .set(
            {
                "conversation": turns,
                "conversation_updated_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )
    )


async def clear_history(user_id: str) -> None:
    """Delete the stored conversation history for a user."""
    db = _get_db()
    await (
        db.collection("users")
        .document(_doc_id(user_id))
        .set(
            {
                "conversation": firestore.DELETE_FIELD,
                "conversation_updated_at": firestore.DELETE_FIELD,
            },
            merge=True,
        )
    )
    logger.info("Cleared conversation history for user=%s", user_id)
