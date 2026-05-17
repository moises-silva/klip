"""Card v2 response builders for Google Chat via the Workspace Add-ons framework."""

from .config import settings

THINKING_PHRASES = [
    "Connecting the dots...",
    "Reading between the lines...",
    "Clipping through the knowledge-verse...",
    "Good things take a moment...",
    "Almost there... probably...",
    "Your patience is appreciated!",
    "Pulling the threads together...",
    "Thinking very hard thoughts...",
    "On the case!",
    "Gathering intelligence...",
    "Making sense of it all...",
    "Piecing it all together...",
    "Scanning for what matters...",
    "Assembling the relevant bits...",
    "Consulting the archives...",
    "Chasing down the answer...",
    "Consulting my inner oracle...",
    "Summoning the answer from the void...",
    "Performing digital alchemy...",
    "Rearranging ones and zeros...",
    "Crunching numbers that don't technically exist...",
    "Loading wisdom... 73%...",
    "Defragmenting my thoughts...",
    "Separating signal from noise...",
    "Following the breadcrumbs...",
    "Untangling the spaghetti...",
    "Mining for gold in a mountain of data...",
    "Working on it. Seriously.",
    "Not procrastinating. Definitely not.",
    "Totally not guessing...",
    "Please don't tap the glass...",
    "The hamster wheel is spinning...",
    "Running a background check on the facts...",
    "Bending the rules of time (slightly)...",
    "Asking the neurons nicely...",
    "My gears are turning (metaphorically)...",
    "Running on caffeine and matrix math...",
    "Channeling my inner genius...",
    "Synthesizing brilliance from thin air...",
    "Brewing something good...",
    "Worth the wait, probably...",
    "The suspense is intentional...",
    "Fast is relative...",
    "Time is an illusion. Answers are not.",
    "If you can read this, I'm still thinking...",
    "Engaging warp drive...",
    "Boldly going where no query has gone before...",
    "Calculating trajectory...",
    "I'm a professional, I promise...",
    "Triangulating the truth...",
    "Mapping the territory...",
    "Weaving the answer together...",
    "Connecting the cosmic dots...",
    "Decoding the universe, one question at a time...",
    "Holding multiple thoughts simultaneously...",
    "Taking the scenic route to your answer...",
    "Finding signal in the static...",
    "Cooking up something clever...",
    "All neurons on deck...",
    "The wheels are in motion...",
    "Connecting neurons at unprecedented speeds...",
    "Letting the ideas percolate...",
    "Big things are happening back here...",
    "Buffering... but make it smart...",
    "Patience: engaged.",
    "This one requires my full horsepower...",
    "Giving this the attention it deserves...",
    "This answer won't write itself. (Well, actually it will.)",
    "Connecting dots you didn't know existed...",
    "Hold tight, something good is coming...",
    "Calibrating for maximum usefulness...",
    "Spinning up the genius...",
    "Reaching into the digital ether...",
    "Turning your question into wisdom...",
    "Contemplating from all angles...",
    "Deep in thought (and loving it)...",
    "Reducing chaos to clarity...",
    "Working backwards from the answer...",
    "Optimizing for brilliance...",
    "Leaving no stone unturned...",
    "Synthesizing a masterpiece...",
    "Doing the heavy lifting so you don't have to...",
    "Precision in progress...",
    "In pursuit of the perfect answer...",
    "Plot twist incoming...",
    "Summoning the muse...",
    "Great minds think... give them a second...",
    "Brainstorming at the speed of light...",
    "Thinking outside the context window...",
    "Running the numbers (and the letters)...",
    "Navigating the labyrinth of knowledge...",
    "Charting a course through the data...",
    "Doing things a search engine only dreams of...",
    "Stand by for incoming brilliance...",
    "Operating at peak wit...",
    "Overthinking it... in a good way...",
    "On it. Whatever 'it' is.",
    "Currently arguing with myself. I'm winning.",
    "Fetching the answer from the cloud... no, the other cloud...",
    "Doing the math. There's a lot of math.",
]


def _chat_action(message_body: dict) -> dict:
    """Wrap a Chat message in the Workspace Add-ons response envelope."""
    return {
        "hostAppDataAction": {
            "chatDataAction": {"createMessageAction": {"message": message_body}}
        }
    }


def welcome_card(auth_url: str) -> dict:
    """Shown on installation or when the user has not yet authorized."""
    return _chat_action(
        {
            "text": (
                "Hi! I'm Klip, your Google Workspace assistant. 👋\n\n"
                "I can help you search conversations, summarize threads, find contacts, "
                "and a whole lot more — but first I'll need permission to access your Workspace data. "
                "It only takes a moment!\n\n"
                "You can execute the '/Configure' command to select the services you want to connect.\n"
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
            ],
        }
    )


def thinking_card(phrase: str) -> dict:
    """Shown while Gemini is working. Sent and updated via the Chat REST API (not Add-ons envelope)."""
    if settings.klip_gif_url:
        card = {
            "header": {
                "title": "",
                "subtitle": phrase,
                "imageUrl": settings.klip_gif_url,
                "imageType": "CIRCLE",
                "imageAltText": "Klip is thinking",
            }
        }
    else:
        card = {
            "sections": [
                {
                    "widgets": [
                        {
                            "decoratedText": {
                                "text": f"<i>{phrase}</i>",
                                "wrapText": False,
                            }
                        }
                    ]
                }
            ]
        }
    return {"cardsV2": [{"cardId": "thinking-card", "card": card}]}


def reauth_card(auth_url: str) -> dict:
    """Shown when a mid-conversation tool call fails due to missing OAuth scopes.
    Returned as a REST API message body (not the Add-ons envelope) so it can
    replace the thinking card in place via update_message."""
    return {
        "text": "",
        "cardsV2": [
            {
                "cardId": "reauth-card",
                "card": {
                    "header": {
                        "title": "Additional permissions needed",
                        "subtitle": "Klip needs more access to complete this request.",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Re-authorize Klip",
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
        ],
    }


def services_changed_card(auth_url: str) -> dict:
    """Sent via the Chat REST API when the user enables new services that need new OAuth scopes."""
    return {
        "text": "",
        "cardsV2": [
            {
                "cardId": "services-changed-card",
                "card": {
                    "header": {
                        "title": "Re-authorization needed",
                        "subtitle": "Your Workspace service configuration has changed.",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": "Your Workspace service configuration has changed. Please re-authorize Klip so your permissions match your updated settings."
                                    }
                                },
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
                                },
                            ]
                        }
                    ],
                },
            }
        ],
    }


def text_response(message: str) -> dict:
    return _chat_action({"text": message})


_MCP_SERVERS = [
    ("chat", "Google Chat"),
    ("people", "Google Contacts"),
    ("gmail", "Gmail"),
    ("calendar", "Google Calendar"),
    ("drive", "Google Drive"),
]


def settings_dialog(
    enabled_servers: list[str] | None = None, debug_enabled: bool = False
) -> dict:
    """Dialog opened by the /settings quick command.

    enabled_servers: list of server keys currently enabled for this user.
    None means all are enabled (no preference saved yet).
    debug_enabled: current value of the user's per-user debug toggle.
    The Debug section is only rendered when settings.debug_chat is True.
    """
    return {
        "action": {
            "navigations": [
                {
                    "pushCard": {
                        "header": {"title": "Settings"},
                        "sections": [
                            {
                                "widgets": [
                                    {
                                        "textParagraph": {
                                            "text": "<i>Note: saving settings resets Klip's memory of previous conversations.</i>"
                                        }
                                    }
                                ],
                            },
                            {
                                "widgets": [
                                    {
                                        "textParagraph": {
                                            "text": "<b>Workspace Services</b>"
                                        }
                                    },
                                    {
                                        "selectionInput": {
                                            "name": "mcp_servers",
                                            "label": "Enable access to these services",
                                            "type": "CHECK_BOX",
                                            "items": [
                                                {
                                                    "text": label,
                                                    "value": key,
                                                    "selected": enabled_servers is None
                                                    or key in enabled_servers,
                                                }
                                                for key, label in _MCP_SERVERS
                                            ],
                                        }
                                    },
                                ],
                            },
                            *(
                                [
                                    {
                                        "widgets": [
                                            {"textParagraph": {"text": "<b>Debug</b>"}},
                                            {
                                                "selectionInput": {
                                                    "name": "debug_chat",
                                                    "type": "CHECK_BOX",
                                                    "items": [
                                                        {
                                                            "text": "Enable",
                                                            "value": "true",
                                                            "selected": debug_enabled,
                                                        }
                                                    ],
                                                }
                                            },
                                        ],
                                    }
                                ]
                                if settings.debug_chat
                                else []
                            ),
                            {
                                "widgets": [
                                    {
                                        "buttonList": {
                                            "buttons": [
                                                {
                                                    "text": "Save",
                                                    "onClick": {
                                                        "action": {
                                                            "function": f"{settings.app_base_url}/events",
                                                            "parameters": [
                                                                {
                                                                    "key": "actionName",
                                                                    "value": "save_settings",
                                                                }
                                                            ],
                                                        }
                                                    },
                                                }
                                            ]
                                        }
                                    },
                                ],
                            },
                        ],
                    }
                }
            ]
        }
    }


def settings_dialog_ok() -> dict:
    """Response to a SUBMIT_DIALOG — shows a notification and closes the dialog."""
    return {
        "action": {
            "navigations": [{"endNavigation": {"action": "CLOSE_DIALOG"}}],
            "notification": {"text": "Settings saved!"},
        }
    }
