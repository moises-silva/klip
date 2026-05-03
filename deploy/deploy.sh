#!/usr/bin/env bash
# deploy.sh — Build and deploy Klip to Cloud Run.
# Usage: GCP_PROJECT=my-project [REGION=us-central1] bash deploy/deploy.sh
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:?Set GCP_PROJECT before running this script}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="klip"
SA_EMAIL="${SERVICE_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${SERVICE_NAME}/app:latest"

# Derive the project number (needed for the gsuiteaddons token issuer)
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
ADDON_TOKEN_ISSUER="service-${PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"

echo "==> Building image: ${IMAGE}"
gcloud builds submit \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_IMAGE=${IMAGE}" \
  --project="${PROJECT_ID}"

echo "==> Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="${SA_EMAIL}" \
  --set-secrets="OAUTH_CLIENT_ID=oauth-client-id:latest,OAUTH_CLIENT_SECRET=oauth-client-secret:latest" \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},REGION=${REGION},GEMINI_MODEL=gemini-2.5-flash,VERIFY_ADDON_TOKENS=true" \
  --project="${PROJECT_ID}"

# Retrieve the stable Cloud Run URL and bake it back into the service as
# APP_BASE_URL and ADDON_AUDIENCE (needed for OAuth and JWT verification).
URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo "==> Setting APP_BASE_URL, ADDON_AUDIENCE, and ADDON_TOKEN_ISSUER..."
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars="APP_BASE_URL=${URL},ADDON_AUDIENCE=${URL}/events,ADDON_TOKEN_ISSUER=${ADDON_TOKEN_ISSUER}"

echo ""
echo "==> Deployment complete!"
echo ""
echo "  Service URL:    ${URL}"
echo "  Events endpoint: ${URL}/events"
echo "  Health check:   ${URL}/health"
echo ""
echo "Register '${URL}/events' as the HTTP endpoint in your Workspace Add-on configuration."
