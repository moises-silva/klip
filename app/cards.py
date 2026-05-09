"""Card v2 response builders for Google Chat via the Workspace Add-ons framework."""

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


def text_response(message: str) -> dict:
    return _chat_action({"text": message})
