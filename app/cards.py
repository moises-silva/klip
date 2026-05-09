"""Card v2 response builders for Google Chat via the Workspace Add-ons framework."""
from .config import settings

THINKING_PHRASES = [
    "Clipping through your conversations...",
    "Pulling the threads together...",
    "Sifting through your Workspace...",
    "Connecting the dots...",
    "Reading between the lines...",
    "Mining your messages (the good kind)...",
    "Rummaging through your inbox...",
    "Assembling the relevant bits...",
    "Consulting the archives...",
    "Untangling the conversation threads...",
    "Thinking very hard thoughts...",
    "Almost there... probably...",
    "Searching your digital filing cabinet...",
    "Making sense of it all...",
    "Your patience is appreciated!",
    "Good things take a moment...",
    "Piecing it all together...",
    "Gathering intelligence...",
    "Scanning for what matters...",
]

def _chat_action(message_body: dict) -> dict:
    """Wrap a Chat message in the Workspace Add-ons response envelope."""
    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": message_body
                }
            }
        }
    }


def welcome_card(auth_url: str) -> dict:
    """Shown on installation or when the user has not yet authorized."""
    return _chat_action({
        "text": (
            "Hi! I'm Klip, your Google Workspace assistant. 👋\n\n"
            "I can help you search conversations, summarize threads, find contacts, "
            "and a whole lot more — but first I'll need permission to access your Workspace data. "
            "It only takes a moment!"
        ),
        "cardsV2": [
            {
                "cardId": "auth-card",
                "card": {
                    "header": {
                        "title": "Klip — Authorization Required",
                        "subtitle": "Grant access to your Workspace data to get started.",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Authorize Klip",
                                                "onClick": {
                                                    "openLink": {"url": auth_url}
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    })


def thinking_card(phrase: str) -> dict:
    """Shown while Gemini is working. Sent and updated via the Chat REST API (not Add-ons envelope)."""
    if settings.klip_gif_url:
        section = {
            "widgets": [
                {
                    "columns": {
                        "columnItems": [
                            {
                                "horizontalSizeStyle": "FILL_MINIMUM_SPACE",
                                "horizontalAlignment": "START",
                                "verticalAlignment": "CENTER",
                                "widgets": [
                                    {"image": {"imageUrl": settings.klip_gif_url, "altText": "Klip is thinking"}}
                                ],
                            },
                            {
                                "horizontalSizeStyle": "FILL_AVAILABLE_SPACE",
                                "horizontalAlignment": "START",
                                "verticalAlignment": "CENTER",
                                "widgets": [
                                    {"decoratedText": {"text": f"<i>{phrase}</i>", "wrapText": False}}
                                ],
                            },
                        ]
                    }
                }
            ]
        }
    else:
        section = {"widgets": [{"decoratedText": {"text": f"<i>{phrase}</i>", "wrapText": False}}]}
    return {"cardsV2": [{"cardId": "thinking-card", "card": {"sections": [section]}}]}


def text_response(message: str) -> dict:
    return _chat_action({"text": message})
