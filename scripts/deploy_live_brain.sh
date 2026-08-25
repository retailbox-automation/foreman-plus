#!/usr/bin/env bash
# Deploy the Gemini Live guidance brain (live_brain/) as Cloud Run service
# `foreman-brain` — auth-only; the glasses bridge calls it with an ID token.
# Vertex auth = the runtime service account (ADC), no keys.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT="${DEPLOY_ACCOUNT:-foreman-agent@foreman-hackathon.iam.gserviceaccount.com}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/live_brain"
cp "$ROOT"/live_brain/*.py "$ROOT"/live_brain/requirements.txt "$STAGE/live_brain/"
cp "$ROOT/live_brain/Dockerfile" "$STAGE/Dockerfile"

ENV="GOOGLE_CLOUD_PROJECT=foreman-hackathon,GOOGLE_GENAI_USE_VERTEXAI=TRUE"
# Native take_photo tool: the glasses bridge is the brain's hands.
if [[ -n "${GLASS_BRIDGE_DEBUG_KEY:-}" ]]; then
  ENV="${ENV},GLASS_BRIDGE_URL=${GLASS_BRIDGE_URL:-https://foreman-glass-112293816563.us-central1.run.app},GLASS_BRIDGE_DEBUG_KEY=${GLASS_BRIDGE_DEBUG_KEY}"
fi

gcloud run deploy foreman-brain \
  --source "$STAGE" \
  --region us-central1 --project foreman-hackathon \
  --account "$ACCOUNT" \
  --no-allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 512Mi \
  --update-env-vars "$ENV"

gcloud run services describe foreman-brain --region us-central1 \
  --project foreman-hackathon --account "$ACCOUNT" \
  --format='value(status.latestReadyRevisionName, status.url)'
