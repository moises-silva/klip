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


settings = Settings()
