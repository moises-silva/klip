# Klip

<img src="https://storage.googleapis.com/klip-static/avatar.png" alt="Klip" width="96" />

Klip is an open-source Google Chat App that acts as a personal Workspace assistant powered by Gemini. Users interact with it via Google Chat DMs. It reads and searches their Workspace data through the Google Chat MCP server and responds using a Gemini model running on Vertex AI.

Klip is designed to be self-hosted by a company or individual on their own GCP infrastructure.

## How it works

1. User sends a message to the Klip bot in Google Chat
2. Google delivers the event to Klip's HTTP endpoint
3. Klip fetches the user's OAuth token from Firestore and connects to the Google Chat MCP server on their behalf
4. Gemini runs a tool-calling loop, querying Workspace data as needed
5. Klip sends the response back to the user in Chat

On first use, Klip prompts the user to authorize via OAuth 2.0. Tokens are stored in Firestore and refreshed automatically.

## Prerequisites

- A GCP project with billing enabled
- A Google Workspace account (for testing Chat events)
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated
- Docker (for building the container image)
- Python 3.12+ and a virtual environment (for local development)
- Enrollment in Google's [Developer Preview Program](https://developers.google.com/workspace/preview) for MCP tool invocation

---

## Option A: Cloud Run deployment (production)

This is the standard self-hosted setup. The app runs on Cloud Run; all GCP services are managed automatically.

### 1. Configure OAuth credentials

In [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → Credentials**:

1. Create an **OAuth 2.0 Client ID** (Web application type)
2. Leave the redirect URIs blank for now — you'll add the Cloud Run URL after the first deploy
3. Copy the client ID and secret

### 2. Bootstrap GCP infrastructure

Run the one-time setup script. This enables APIs, creates the service account, Firestore database, Artifact Registry repository, and Secret Manager secrets:

```bash
GCP_PROJECT=your-project-id bash deploy/setup.sh
```

Then store your OAuth credentials in Secret Manager:

```bash
printf 'YOUR_CLIENT_ID'     | gcloud secrets versions add oauth-client-id     --data-file=- --project=your-project-id
printf 'YOUR_CLIENT_SECRET' | gcloud secrets versions add oauth-client-secret  --data-file=- --project=your-project-id
```

### 3. Deploy

```bash
GCP_PROJECT=your-project-id bash deploy/deploy.sh
```

The script builds the container, deploys to Cloud Run, then retrieves the stable service URL and sets `APP_BASE_URL`, `ADDON_AUDIENCE`, and `ADDON_TOKEN_ISSUER` automatically.

### 4. Register the OAuth redirect URI

Back in Cloud Console → **Credentials → your OAuth client**, add:

```
https://YOUR_CLOUD_RUN_URL/auth/callback
```

### 5. Configure the Workspace Add-on

In Cloud Console → **Google Workspace Add-ons** (or **Chat API → Configuration**):

- Set the HTTP endpoint URL to: `https://YOUR_CLOUD_RUN_URL/events`
- Upload `deploy/addon.json` as the deployment descriptor

### 6. Install and test

Install the add-on for your Google Workspace and send a message to the Klip bot in Google Chat.

---

## Option B: Hybrid development setup (VPS + Apache)

This setup runs the Python app on your own server (e.g. a DigitalOcean VPS) behind Apache, with GCP services (Firestore, Vertex AI, Secret Manager) remaining in the cloud. It gives you a fast edit → reload → test cycle without rebuilding and pushing a container image.

### Architecture

```
Google Chat → HTTPS → Apache (yourdomain.com/klip) → uvicorn (127.0.0.1:9000) → GCP
```

### 1. Set up a Python virtual environment on the VPS

```bash
git clone <this-repo> && cd gchat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Apache as a reverse proxy

Add the following inside your HTTPS `<VirtualHost>` block (port 443):

```apache
ProxyPreserveHost On
ProxyPass        /klip/ http://127.0.0.1:9000/
ProxyPassReverse /klip/ http://127.0.0.1:9000/
```

`mod_proxy` and `mod_proxy_http` must be enabled:

```bash
sudo a2enmod proxy proxy_http
sudo systemctl reload apache2
```

### 3. Create your local `.env`

```bash
cp .env.example .env
```

Edit `.env` with your values:

```dotenv
GCP_PROJECT=your-project-id
REGION=us-central1
GEMINI_MODEL=gemini-2.5-flash

OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
OAUTH_CLIENT_SECRET=your-client-secret

APP_BASE_URL=https://yourdomain.com/klip
ADDON_AUDIENCE=https://yourdomain.com/klip/events
ADDON_TOKEN_ISSUER=service-PROJECT_NUMBER@gcp-sa-gsuiteaddons.iam.gserviceaccount.com

VERIFY_ADDON_TOKENS=true
```

Find your project number with:

```bash
gcloud projects describe your-project-id --format="value(projectNumber)"
```

### 4. Authenticate with GCP (Application Default Credentials)

Vertex AI and Firestore use ADC for authentication — no service account key file needed.

On the VPS, run:

```bash
gcloud auth application-default login --no-browser
```

It prints a `gcloud auth application-default login` command to run on a machine that has a browser (e.g. your laptop). Running that command opens a browser window, and after you authenticate it prints an authorization URL. Copy that URL and paste it back into the VPS terminal to complete the process. Credentials are saved to `~/.config/gcloud/application_default_credentials.json`.

### 5. Grant your personal account Vertex AI access

The Cloud Run service account already has the right IAM roles. For local development, grant your own account the same:

```bash
gcloud projects add-iam-policy-binding your-project-id \
  --member="user:you@example.com" \
  --role="roles/aiplatform.user"
```

### 6. Register the OAuth redirect URI and update the Chat endpoint

In Cloud Console → **Credentials → your OAuth client**, add:

```
https://yourdomain.com/klip/auth/callback
```

In **Chat API → Configuration**, set the events endpoint to:

```
https://yourdomain.com/klip/events
```

> To switch back to Cloud Run, change this URL back to the Cloud Run URL.

### 7. Run the app

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```

`--reload` watches `.py` files and restarts automatically. Changes to `.env` require a manual restart.

### 8. Verify

```bash
curl https://yourdomain.com/klip/health
# {"status":"ok"}
```

Watch live logs from Apache and the app:

```bash
sudo tail -f /var/log/apache2/error.log /var/log/apache2/access.log
```

---

## Environment variable reference

See `.env.example` for the full list with descriptions.

| Variable | Required | Notes |
|----------|----------|-------|
| `GCP_PROJECT` | Yes | GCP project ID |
| `REGION` | No | Defaults to `us-central1` |
| `GEMINI_MODEL` | No | Defaults to `gemini-2.5-flash` |
| `OAUTH_CLIENT_ID` | Yes | From Cloud Console credentials |
| `OAUTH_CLIENT_SECRET` | Yes | From Cloud Console credentials (use Secret Manager in Cloud Run) |
| `APP_BASE_URL` | Yes | Public base URL, no trailing slash |
| `ADDON_AUDIENCE` | Yes | `APP_BASE_URL/events` |
| `ADDON_TOKEN_ISSUER` | Yes | `service-{PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com` |
| `VERIFY_ADDON_TOKENS` | No | Defaults to `true`. Always `true` in production. |
| `DEBUG_GEMINI` | No | Set to `true` for verbose Gemini SDK and MCP transport logs |

## Testing the MCP connection

A test script is included to verify your MCP setup at various levels without needing a live Chat event:

```bash
# Levels 0–4: ADC check, handshake, tool list, tool call
python scripts/test_mcp.py --level 2
```

## Future work

See `TODO.md`.
