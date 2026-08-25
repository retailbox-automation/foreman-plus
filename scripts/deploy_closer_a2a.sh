#!/usr/bin/env bash
# Deploy the closer agent as its OWN Cloud Run service (foreman-closer),
# exposed over the A2A protocol via to_a2a() — agent card at
# /.well-known/agent-card.json. Boundary chosen for independent deploy/scale.
#
# First deploy needs FOREMAN_DB_URL_PROD in the caller's environment (the
# Cloud SQL socket DSN); later deploys reuse the revision's env when unset.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT="${DEPLOY_ACCOUNT:-foreman-agent@foreman-hackathon.iam.gserviceaccount.com}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
rsync -a --exclude '__pycache__' "$ROOT/foreman_app" "$STAGE/"
cp "$ROOT/foreman_app/requirements.txt" "$STAGE/requirements.txt"
printf 'web: uvicorn foreman_app.a2a_app:a2a_app --host 0.0.0.0 --port $PORT\n' \
  > "$STAGE/Procfile"

ENV_FLAGS=()
if [[ -n "${FOREMAN_DB_URL_PROD:-}" ]]; then
  ENV_FLAGS+=(--set-env-vars
    "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,GOOGLE_CLOUD_PROJECT=foreman-hackathon,FOREMAN_DB_URL=${FOREMAN_DB_URL_PROD}")
fi

gcloud run deploy foreman-closer \
  --source "$STAGE" \
  --region us-central1 --project foreman-hackathon \
  --account "$ACCOUNT" \
  --allow-unauthenticated \
  --add-cloudsql-instances foreman-hackathon:us-central1:foreman-pg \
  --max-instances 1 \
  "${ENV_FLAGS[@]}"

gcloud run services describe foreman-closer --region us-central1 \
  --project foreman-hackathon --account "$ACCOUNT" \
  --format='value(status.latestReadyRevisionName, status.url)'
