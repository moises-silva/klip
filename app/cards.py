"""Card v2 response builders for Google Chat."""


def welcome_card(auth_url: str) -> dict:
    """Card shown on installation or when the user has not yet authorized."""
    return {
        "cardsV2": [{
            "cardId": "welcome",
            "card": {
                "header": {
                    "title": "Klip",
                    "subtitle": "Your AI-powered Google Workspace helper",
                },
                "sections": [{
                    "widgets": [
                        {
                            "textParagraph": {
                                "text": (
                                    "Hi! I can help you summarize conversations, "
                                    "search messages, and more — right from Google Chat.\n\n"
                                    "To get started, please authorize me to access "
                                    "your Workspace data."
                                )
                            }
                        },
                        {
                            "buttonList": {
                                "buttons": [{
                                    "text": "Authorize Access",
                                    "onClick": {"openLink": {"url": auth_url}},
                                }]
                            }
                        },
                    ]
                }],
            },
        }]
    }


def text_response(message: str) -> dict:
    return {"text": message}
