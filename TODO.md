# Klip — TODO / Ideas

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

## Multi-turn conversation history

Each message is currently an independent prompt — no memory of prior turns in the 1:1 conversation.

**How it would work:**
- Store conversation history in Firestore as a list of `{role, text}` turns per user
- Load history at the start of `respond()` and prepend to `contents`
- Append the new user message and model response after each turn
- Cap history length to avoid unbounded context growth (e.g. last N turns or token budget)
