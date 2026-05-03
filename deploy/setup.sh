#!/usr/bin/env bash
# setup.sh — One-time GCP project bootstrap for Klip.
# Run once per GCP project before the first deployment.
# Usage: GCP_PROJECT=my-project [REGION=us-central1] bash deploy/setup.sh
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:?Set GCP_PROJECT before running this script}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="klip"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Bootstrapping project: ${PROJECT_ID} (region: ${REGION})"

# ------------------------------------------------------------------
# APIs
# ------------------------------------------------------------------
echo "==> Enabling GCP APIs..."
gcloud services enable \
  chat.googleapis.com \
  people.googleapis.com \
  gsuiteaddons.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  aiplatform.googleapis.com \
  --project="${PROJECT_ID}"

# ------------------------------------------------------------------
# Service account
# ------------------------------------------------------------------
echo "==> Service account: ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Klip" \
    --project="${PROJECT_ID}"
  echo "    Created."
else
  echo "    Already exists."
fi

echo "==> Granting IAM roles..."
for ROLE in \
  roles/datastore.user \
  roles/secretmanager.secretAccessor \
  roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet
  echo "    Granted ${ROLE}"
done

# ------------------------------------------------------------------
# Firestore (native mode)
# ------------------------------------------------------------------
echo "==> Firestore..."
if ! gcloud firestore databases describe --project="${PROJECT_ID}" &>/dev/null; then
  gcloud firestore databases create \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
  echo "    Created in ${REGION}."
else
  echo "    Already exists."
fi

# ------------------------------------------------------------------
# Artifact Registry
# ------------------------------------------------------------------
echo "==> Artifact Registry repository: ${SERVICE_NAME}"
if ! gcloud artifacts repositories describe "${SERVICE_NAME}" \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud artifacts repositories create "${SERVICE_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
  echo "    Created."
else
  echo "    Already exists."
fi

# ------------------------------------------------------------------
# Secret Manager — placeholder secrets (must be updated before deploy)
# ------------------------------------------------------------------
echo "==> Secret Manager secrets..."
for SECRET in oauth-client-id oauth-client-secret; do
  if ! gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" &>/dev/null; then
    printf 'PLACEHOLDER' | gcloud secrets create "${SECRET}" \
      --data-file=- \
      --project="${PROJECT_ID}"
    echo "    Created: ${SECRET}  ← update with real value"
  else
    echo "    Exists:  ${SECRET}"
  fi
done

# ------------------------------------------------------------------
echo ""
echo "==> Bootstrap complete!"
echo ""
echo "Next: update secrets, then deploy."
echo ""
echo "  Update secrets:"
echo "    printf 'YOUR_ID'  | gcloud secrets versions add oauth-client-id --data-file=- --project=${PROJECT_ID}"
echo "    printf 'YOUR_SEC' | gcloud secrets versions add oauth-client-secret --data-file=- --project=${PROJECT_ID}"
echo ""
echo "  Deploy:"
echo "    GCP_PROJECT=${PROJECT_ID} REGION=${REGION} bash deploy/deploy.sh"
