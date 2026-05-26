# Klip — Requirements

## Overview

An open-source Google Chat App called **Klip** (a nod to the classic Clippy assistant) that acts as
a Workspace Personal Assistant powered by Gemini. Users install the App into Google Chat and
interact with it via 1:1 DMs. The app is designed to be self-hosted by companies on their own GCP
infrastructure.

## Deployment Model

- **Open source** — companies self-host on GCP
- **HTTP-based** — no Apps Script; the app is an HTTP server receiving JSON webhook events
- **Framework** — Google Workspace Addons (supports multiple surfaces; Chat is the first)
- **Initial surface** — Google Chat 1:1 DMs only

## Onboarding & Configuration

1. When a user installs the App (ADDED_TO_SPACE event in a DM), the App immediately sends a welcome
   message explaining what it does and prompting the user to complete configuration.
1. Configuration = OAuth authorization. The welcome card includes a button that initiates an OAuth
   2.0 flow requesting the required scopes.
1. The OAuth callback stores the user's tokens (access + refresh) associated with their Google
   identity.

## OAuth Scopes

### Google Workspace MCP — Chat tools

| Tool                        | Required scopes                                          |
| --------------------------- | -------------------------------------------------------- |
| list_messages               | `https://www.googleapis.com/auth/chat.messages.readonly` |
| search_messages             | `https://www.googleapis.com/auth/chat.messages.readonly` |
| send_message                | `https://www.googleapis.com/auth/chat.messages`          |
| find_conversations (spaces) | `https://www.googleapis.com/auth/chat.spaces.readonly`   |

### Google Workspace MCP — People tools

| Purpose                    | Required scopes                                      |
| -------------------------- | ---------------------------------------------------- |
| Resolve names / identities | `https://www.googleapis.com/auth/contacts.readonly`  |
| Org directory lookup       | `https://www.googleapis.com/auth/directory.readonly` |

## AI Model

- **Primary model**: Gemini (Vertex AI or Google AI Studio key; operator-configurable)
- Default model: `gemini-2.0-flash` (cheapest capable model with function calling; operator may
  override via `GEMINI_MODEL` env var)
- End users cannot change the model — only the operator/developer can

## MCP Architecture

The app acts as an **MCP host** (not a server). Data flow:

```
User (Chat DM)
    ↓ HTTPS webhook event
Our App (FastAPI / Cloud Run)
    ↓ Gemini SDK (function calling)
Gemini model
    ↓ tool invocation requests
Our App (dispatches tool calls)
    ↓ HTTP MCP protocol (user's OAuth token)
Remote Google Workspace MCP servers
    e.g. chatmcp.googleapis.com (Chat tools)
         [people MCP endpoint TBD] (People/directory tools)
```

- **Transport**: HTTP (streamable HTTP or SSE) — not stdio
- **Authentication to MCP servers**: user's delegated OAuth access token passed in
  `Authorization: Bearer` header on each MCP request
- The official Google Workspace MCP servers are used — no third-party MCP servers
- **MCP client library**: official Python `mcp` SDK (`mcp` on PyPI)

## MVP Features

### 1. Summarize conversations in a space

- User says: _"Summarize my conversations in space Engineering"_
- App uses `find_conversations` to locate the space, then `list_messages` to retrieve messages, then
  asks Gemini to produce a summary
- App replies in Chat with the summary

### 2. Search messages with filters

- User says: _"Find all bug messages from last week"_
- App uses `search_messages` with a time-range filter (last 7 days) and a keyword filter ("bug")
- App returns a formatted list of matching messages with links

## GCP Infrastructure Recommendations

### For self-hosted production deployments (what companies would deploy)

| Component             | GCP Service               | Rationale                                                              |
| --------------------- | ------------------------- | ---------------------------------------------------------------------- |
| App runtime           | Cloud Run                 | Serverless; scales to zero; easy container deployment                  |
| Token & session store | Firestore (Native mode)   | Serverless NoSQL; no infra to manage; good for key-value token storage |
| Secrets               | Secret Manager            | API keys, OAuth client secret, Gemini key                              |
| Container registry    | Artifact Registry         | Store and version Docker images                                        |
| CI/CD                 | Cloud Build               | Build + deploy pipeline, triggered on push                             |
| Service identity      | Service Account           | Least-privilege access from Cloud Run to Firestore / Secret Manager    |
| Networking            | Cloud Run default (HTTPS) | Built-in TLS; no load balancer needed for MVP                          |

### For maintainer/tester deployment (personal GCP project)

Same stack as above but in a personal GCP project. A single `make deploy` (via `gcloud run deploy`)
is sufficient. No VPC or separate environment required for initial testing.

## Security Requirements

- OAuth tokens stored encrypted at rest in Firestore (GCP default encryption)
- All secrets (Gemini key, OAuth client secret) stored in Secret Manager, never in environment
  variables or source code
- The app verifies the `X-Goog-Signature` header on all incoming webhook requests to authenticate
  that events come from Google
- Least-privilege service account: Cloud Run SA gets only Firestore write + Secret Manager accessor
  roles

## Non-Requirements (Deferred)

- Multi-workspace / multi-tenant token isolation beyond per-user Firestore docs
- Rate limiting or quota management per user
- Google Docs / Meet surfaces (planned for future phases)
- Fine-grained conversation history / memory persistence
- Custom persona or system prompt configuration per deployment (future)
- Marketplace listing / admin installation (future — internal installation for now)

## Open Questions

- Which MCP transport does the official Google Workspace MCP server use (stdio vs. HTTP)? This
  affects whether it runs as a sidecar container or separate Cloud Run service.
- Exact Gemini model ID to default to (e.g., `gemini-2.0-flash`, `gemini-1.5-pro`).
- OAuth redirect URI hosting — the Cloud Run URL will be the redirect URI; needs to be registered in
  the OAuth consent screen.
