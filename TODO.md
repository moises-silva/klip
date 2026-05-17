# Klip — TODO / Ideas

## Google Search integration

The Gemini API does not support mixing `google_search` with `function_declarations` in the same
request — they are mutually exclusive. Two approaches to resolve this:

**Option A — Explicit phrase trigger (recommended)** Detect a set of natural web-search phrases in
the user message ("search the web", "google", "look up online", "latest news", etc.) and switch to
`google_search`-only mode for those requests. Zero extra latency, no misclassification risk.
Discoverability requires documenting the trigger phrases in the onboarding/help message.

**Option B — Intent detection via Gemini pre-call** Fire a cheap, no-tool Gemini call to classify
the intent as "workspace" or "web" before the main call. Cleaner UX but adds a full round-trip to
every message, breaks on mixed-intent queries (e.g. "find news about the person who emailed me"),
and risks silent misclassification.

## Local development tunnel

Set up a public URL that maps to a local Python server so Chat events can be tested without
deploying to Cloud Run. Eliminates the build/push/deploy cycle and enables `uvicorn --reload` +
debugger during development.

**How it would work:**

- Run a tunnel tool (ngrok paid for stable URL, or Cloudflare Tunnel with own domain)
- Re-point the Workspace Add-on deployment at the tunnel URL (one-time with stable URL)
- Add tunnel URL as additional OAuth redirect URI in Cloud Console
- Local `.env`: set `VERIFY_ADDON_TOKENS=false`, `APP_BASE_URL=https://your-tunnel`
- ADC already works via `gcloud auth application-default login`
- Firestore connects to the real GCP instance (or Firestore emulator for full isolation)

# Configuration & Personalization

Allow users to use a /config command to tweak settings such as:

- Enable/Disable MCP tools/servers (disable completely an MCP server such as gmail or just specific
  tools)
- User prompt context / preferences

This could be either via slash command with invoke dialog or in the 'Home' tab for the App (is this
supported for Chat Addons?)

# Reset Auth Command

/reset_auth slash or quick commadn to reset authorization, but not the rest of the settings (like
the current reset command does)

# Comparison Table with native 'Ask Gemini'

Write a few words about how this App is different from the native 'Ask Gemini' by Google (tl;dr this
is a 2P tool customers can build on top of and customize)

# Extensibility

How do we make this App extensible (e.g plugins?) as a foundation to build on

# White labeling

Make sure is easy to change the branding information easily (beyond just the App config). This
likely includes adjustments to some prompts and card titles.

# Bugs

- Only request the oauth scopes needed based on the services enabled in the App settings

- It seems a prompt like "What is the latest email I have received?" causes two types of
  misbehavior.

  - Using gemini flash the model confuses the OrderBy parameter from the Chat tool search_messages
    with Gmail search_threads and injects the invalid parameter for search_threads.
  - Even once the invalid parameter is fixed (either using the new strip_unknown_tool_params option
    or using the pro model) it appears Gemini is unable to identify the latest email received,
    instead just shows the latest email thread (including an email sent, not received)
