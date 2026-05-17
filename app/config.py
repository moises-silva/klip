from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project: str = ""
    region: str = "us-central1"

    # Gemini — operator-configurable only; not exposed to end users.
    # Uses Vertex AI (ADC via service account); no API key required.
    gemini_model: str = "gemini-2.5-flash"

    # OAuth 2.0 credentials (from Google Cloud Console)
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    # Public Cloud Run URL; used as OAuth redirect base and in card links.
    app_base_url: str = ""

    # Workspace Add-on JWT verification.
    # addon_audience: the Cloud Run URL Google puts in the JWT "aud" claim.
    addon_audience: str = ""
    # addon_token_issuer: the service account Google signs tokens with.
    # Format: service-{PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com
    addon_token_issuer: str = ""
    # Disable for local development only — must be true in production.
    verify_addon_tokens: bool = True
    # Enable DEBUG logging for the Gemini SDK's agentic loop (noisy, for troubleshooting).
    debug_gemini: bool = False
    # Log full HTTP request/response (headers + body) for MCP calls (very noisy).
    debug_mcp_http: bool = False
    # Seconds before the Gemini agentic loop is cancelled and an error is sent.
    gemini_timeout: int = 60
    # Public URL of the animated GIF shown in the thinking card while Gemini works.
    # Leave empty to omit the image and show only the rotating phrase.
    klip_gif_url: str = ""
    # Strip parameters not declared in a tool's MCP schema before dispatching.
    # Works around Gemini hallucinating extra parameters (e.g. orderBy on gmail_search_threads).
    strip_unknown_tool_params: bool = False
    # Post a debug info message in-thread after every Gemini response (developer use only).
    debug_chat: bool = False
    # Maximum word count for user prompt instructions.
    max_user_prompt_words: int = 250


settings = Settings()
