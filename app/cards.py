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
    # TODO: cardsV2 card rendering could not be made to work with the Workspace
    # Add-ons HTTP event response format — returning plain text with a link instead.
    return _chat_action({
        "text": (
            "Hi! I can help you summarize conversations and search messages. "
            f"To get started, please authorize me to access your Workspace data: "
            f"<{auth_url}|Click here to Authorize>"
        )
    })


def text_response(message: str) -> dict:
    return _chat_action({"text": message})
