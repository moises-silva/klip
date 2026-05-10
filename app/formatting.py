import re


def md_to_chat(text: str) -> str:
    """Convert standard Markdown to Google Chat's formatting subset.

    Chat uses a non-standard subset:
      Bold:          *text*   (single asterisk, not double)
      Italic:        _text_   (single underscore — same as Markdown)
      Strikethrough: ~text~   (single tilde, not double)
      Inline code:   `text`   (same)
      Code block:    ```text``` (same)
      Blockquote:    > text   (same)
      Bullet list:   * item / - item (same)
      Link:          <url|display> (NOT [text](url))

    Transformations applied:
      **bold**       → *bold*
      ~~strike~~     → ~strike~
      [text](url)    → <url|text>
      user@host      → <mailto:user@host|user@host>
      # Heading      → *Heading*  (all heading levels become bold)
      * item         → - item     (asterisk bullets → hyphen to avoid bold ambiguity)
        * sub-item   →     - sub-item  (sub-bullets indented to 4 spaces per level)
      1. item        → - item     (numbered lists become bullets)
    """
    placeholders: dict[str, str] = {}
    counter = 0

    def protect(m: re.Match) -> str:
        nonlocal counter
        key = f"\x00PROTECTED{counter}\x00"
        placeholders[key] = m.group(0)
        counter += 1
        return key

    # Protect code so we never mangle it.
    text = re.sub(r"```[\s\S]*?```", protect, text)
    text = re.sub(r"`[^`\n]+`", protect, text)

    # Bullet lists: convert * to - and normalize indentation to 4 spaces per level.
    # Must run BEFORE bold conversion to avoid asterisk ambiguity ("* *bold*").
    # Gemini uses 2-space indentation; we expand to 4 so sub-bullets are visible in Chat.
    def _bullet(m: re.Match) -> str:
        level = len(m.group(1)) // 2
        return "    " * level + "- "

    text = re.sub(r"^( *)[*-]\s+", _bullet, text, flags=re.MULTILINE)

    # Links: [text](url) → <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Bare email addresses → Gmail compose link.
    # Negative lookbehind excludes emails already inside a <url|display> Chat link,
    # where the address is preceded by | (display part) or < or : (URL part).
    text = re.sub(
        r"(?<![<:/|\w])[\w.+-]+@[\w-]+\.[\w.]+",
        r"<https://mail.google.com/mail/?view=cm&to=\g<0>|\g<0>>",
        text,
    )

    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    # Headers: ## Heading → *Heading*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Numbered lists: "1. item" / "  1. sub" → same hyphen-bullet treatment.
    def _numbered(m: re.Match) -> str:
        level = len(m.group(1)) // 2
        return "    " * level + "- "

    text = re.sub(r"^( *)\d+\.\s+", _numbered, text, flags=re.MULTILINE)

    for key, val in placeholders.items():
        text = text.replace(key, val)

    # Strip backtick wrappers from Chat link URLs and display text.
    # Gemini sometimes writes [`url`](`url`); after placeholder restoration the
    # backticks land inside <url|display>, making the URL invalid (%60 encoding).
    text = re.sub(r"<`([^`|>]+)`\|([^>]*)>", r"<\1|\2>", text)  # backtick URL
    text = re.sub(r"<([^|>]*)\|`([^`>]*)`>", r"<\1|\2>", text)  # backtick display

    # Bare URL in an inline code span: `https://url` → <url|url>
    # Runs after restoration so it catches spans not consumed by link processing.
    # Chat auto-detects URLs inside backtick spans but includes the trailing backtick
    # in the href, producing %60 at the end.
    text = re.sub(r"`(https?://[^`\s]+)`", r"<\1|\1>", text)

    return text
