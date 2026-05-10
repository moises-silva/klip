# Klip — TODO / Ideas

## Google Search integration

The Gemini API does not support mixing `google_search` with `function_declarations` in the same request — they are mutually exclusive. Two approaches to resolve this:

**Option A — Explicit phrase trigger (recommended)**
Detect a set of natural web-search phrases in the user message ("search the web", "google", "look up online", "latest news", etc.) and switch to `google_search`-only mode for those requests. Zero extra latency, no misclassification risk. Discoverability requires documenting the trigger phrases in the onboarding/help message.

**Option B — Intent detection via Gemini pre-call**
Fire a cheap, no-tool Gemini call to classify the intent as "workspace" or "web" before the main call. Cleaner UX but adds a full round-trip to every message, breaks on mixed-intent queries (e.g. "find news about the person who emailed me"), and risks silent misclassification.

## Local development tunnel

Set up a public URL that maps to a local Python server so Chat events can be
tested without deploying to Cloud Run. Eliminates the build/push/deploy cycle
and enables `uvicorn --reload` + debugger during development.

**How it would work:**
- Run a tunnel tool (ngrok paid for stable URL, or Cloudflare Tunnel with own domain)
- Re-point the Workspace Add-on deployment at the tunnel URL (one-time with stable URL)
- Add tunnel URL as additional OAuth redirect URI in Cloud Console
- Local `.env`: set `VERIFY_ADDON_TOKENS=false`, `APP_BASE_URL=https://your-tunnel`
- ADC already works via `gcloud auth application-default login`
- Firestore connects to the real GCP instance (or Firestore emulator for full isolation)

