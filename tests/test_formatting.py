import pytest

from app.formatting import md_to_chat


# --- bold ---

def test_bold_double_asterisk():
    assert md_to_chat("**hello**") == "*hello*"

def test_bold_mid_sentence():
    assert md_to_chat("Say **hello** world") == "Say *hello* world"

def test_bold_multiple():
    assert md_to_chat("**a** and **b**") == "*a* and *b*"

def test_bold_already_single_asterisk_unchanged():
    # Single *text* is already valid Chat bold — leave it alone.
    assert md_to_chat("*hello*") == "*hello*"


# --- strikethrough ---

def test_strikethrough_double_tilde():
    assert md_to_chat("~~cancelled~~") == "~cancelled~"

def test_strikethrough_mid_sentence():
    assert md_to_chat("event ~~cancelled~~ rescheduled") == "event ~cancelled~ rescheduled"

def test_single_tilde_unchanged():
    assert md_to_chat("~hello~") == "~hello~"


# --- links ---

def test_link_converted():
    assert md_to_chat("[Google](https://google.com)") == "<https://google.com|Google>"

def test_link_with_surrounding_text():
    assert md_to_chat("See [docs](https://example.com) for details") == \
        "See <https://example.com|docs> for details"

def test_link_multiple():
    result = md_to_chat("[A](https://a.com) and [B](https://b.com)")
    assert result == "<https://a.com|A> and <https://b.com|B>"

def test_bare_url_unchanged():
    assert md_to_chat("Visit https://example.com now") == "Visit https://example.com now"

def test_link_with_backtick_url():
    # Gemini sometimes writes the URL in backticks; backticks must be stripped
    # from the URL or Chat encodes them as %60 and breaks the link.
    src = "[`https://example.com`](`https://example.com`)"
    assert md_to_chat(src) == "<https://example.com|https://example.com>"

def test_link_with_backtick_display_only():
    src = "[`docs`](https://example.com)"
    assert md_to_chat(src) == "<https://example.com|docs>"

def test_link_with_backtick_url_only():
    src = "[docs](`https://example.com`)"
    assert md_to_chat(src) == "<https://example.com|docs>"

def test_bare_email_converted_to_gmail_compose():
    result = md_to_chat("from moy@example.com today")
    assert result == "from <https://mail.google.com/mail/?view=cm&to=moy@example.com|moy@example.com> today"

def test_bare_email_at_end_of_sentence_no_trailing_dot():
    # Trailing sentence period must not be included in the email match.
    result = md_to_chat("Contact alejandro@example.com. Is this correct?")
    assert result == "Contact <https://mail.google.com/mail/?view=cm&to=alejandro@example.com|alejandro@example.com>. Is this correct?"

def test_bare_email_not_double_converted():
    # An email already inside a markdown link should not get a second wrap.
    src = "[moy@example.com](mailto:moy@example.com)"
    result = md_to_chat(src)
    assert result == "<mailto:moy@example.com|moy@example.com>"


# --- headers ---

def test_h1_becomes_bold():
    assert md_to_chat("# Title") == "*Title*"

def test_h2_becomes_bold():
    assert md_to_chat("## Section") == "*Section*"

def test_h3_becomes_bold():
    assert md_to_chat("### Sub") == "*Sub*"

def test_header_mid_document():
    text = "Intro\n\n## Section\n\nBody"
    assert md_to_chat(text) == "Intro\n\n*Section*\n\nBody"

def test_header_not_matched_mid_line():
    # A # not at line start should not be treated as a header.
    assert md_to_chat("item #1") == "item #1"


# --- numbered lists ---

def test_numbered_list_single():
    assert md_to_chat("1. First item") == "- First item"

def test_numbered_list_multiple():
    text = "1. Alpha\n2. Beta\n3. Gamma"
    assert md_to_chat(text) == "- Alpha\n- Beta\n- Gamma"

def test_asterisk_bullet_converted_to_hyphen():
    assert md_to_chat("* item") == "- item"

def test_hyphen_bullet_unchanged():
    assert md_to_chat("- item") == "- item"

def test_sub_bullet_asterisk_indented():
    # Gemini uses 2-space indent for sub-bullets; we expand to 4.
    text = "* top\n  * sub"
    assert md_to_chat(text) == "- top\n    - sub"

def test_sub_bullet_hyphen_indented():
    text = "- top\n  - sub"
    assert md_to_chat(text) == "- top\n    - sub"

def test_three_level_nesting():
    text = "- top\n  - mid\n    - deep"
    assert md_to_chat(text) == "- top\n    - mid\n        - deep"

def test_nested_list_with_bold():
    text = "* **Section**\n  * **sub-item**"
    assert md_to_chat(text) == "- *Section*\n    - *sub-item*"


# --- code protection ---

def test_inline_code_not_transformed():
    assert md_to_chat("`**not bold**`") == "`**not bold**`"

def test_bare_url_in_code_span():
    # Gemini writes bare URLs in backticks; Chat auto-detects the URL but includes
    # the trailing backtick in the href, producing %60. Convert to a Chat link.
    result = md_to_chat("Links to `https://modelcontextprotocol.io/docs/learn/architecture`")
    assert result == "Links to <https://modelcontextprotocol.io/docs/learn/architecture|https://modelcontextprotocol.io/docs/learn/architecture>"

def test_bare_url_in_code_span_not_double_wrapped():
    # A [`url`](`url`) pattern is handled by the link path; the URL-in-code-span
    # pass should not fire again on the result.
    src = "[`https://example.com`](`https://example.com`)"
    assert md_to_chat(src) == "<https://example.com|https://example.com>"

def test_code_span_non_url_preserved():
    assert md_to_chat("`some_function()`") == "`some_function()`"

def test_code_block_not_transformed():
    text = "```\n**not bold** ~~not strike~~\n```"
    assert md_to_chat(text) == text

def test_code_block_with_language_not_transformed():
    text = "```python\nprint('**hello**')\n```"
    assert md_to_chat(text) == text

def test_content_around_code_block_is_transformed():
    text = "**before**\n```\ncode\n```\n**after**"
    assert md_to_chat(text) == "*before*\n```\ncode\n```\n*after*"


# --- combinations ---

def test_bold_inside_bullet_list():
    # Asterisk list marker is converted to hyphen, then bold ** → * within the item.
    text = "*   **Project Alpha** — status update"
    assert md_to_chat(text) == "- *Project Alpha* — status update"

def test_real_gemini_response():
    text = (
        "Here is what you missed:\n\n"
        "*   **Klip MCP Project** from moy@example.com on May 4.\n"
        "*   **[Preview Program] Features ready** from noreply@google.com on May 4.\n\n"
        "Would you like to know more?"
    )
    result = md_to_chat(text)
    assert "- *Klip MCP Project*" in result
    assert "- *[Preview Program] Features ready*" in result
    assert "**" not in result

def test_link_and_bold_combined():
    assert md_to_chat("**[notes](https://docs.google.com)**") == "*<https://docs.google.com|notes>*"

def test_strikethrough_and_bold():
    assert md_to_chat("**bold** and ~~strike~~") == "*bold* and ~strike~"

def test_plain_text_unchanged():
    text = "Hello, here is a plain response with no markdown."
    assert md_to_chat(text) == text

def test_empty_string():
    assert md_to_chat("") == ""
