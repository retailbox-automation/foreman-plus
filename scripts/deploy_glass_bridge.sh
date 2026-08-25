#!/usr/bin/env bash
# Deploy the Mentra glasses intake bridge (glass_bridge/, bun) as its own
# Cloud Run service `foreman-glass`. min-instances=1: MentraOS Cloud holds a
# long-lived session WebSocket to the bridge — scale-to-zero would drop it.
#
# The Mentra API key is NOT in the repo: pass MENTRAOS_API_KEY in the caller's
# env (Keychain `mentra-foreman-api-key`), or leave unset to reuse the
# revision's stored env on later deploys.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT="${DEPLOY_ACCOUNT:-foreman-agent@foreman-hackathon.iam.gserviceaccount.com}"
FOREMAN_RUN_URL="${FOREMAN_RUN_URL:-https://foreman-hello-112293816563.us-central1.run.app}"

ENV="GOOGLE_CLOUD_PROJECT=foreman-hackathon,PACKAGE_NAME=com.retailbox.foreman,FOREMAN_RUN_URL=${FOREMAN_RUN_URL},FOREMAN_APP_NAME=foreman_app,FOREMAN_USER_ID=glass-tech"
if [[ -n "${MENTRAOS_API_KEY:-}" ]]; then
  ENV="${ENV},MENTRAOS_API_KEY=${MENTRAOS_API_KEY}"
fi
if [[ -n "${LIVE_BRAIN_URL:-}" ]]; then
  ENV="${ENV},LIVE_BRAIN_URL=${LIVE_BRAIN_URL}"
fi
if [[ -n "${DEBUG_KEY:-}" ]]; then
  ENV="${ENV},DEBUG_KEY=${DEBUG_KEY}"
fi

gcloud run deploy foreman-glass \
  --source "$ROOT/glass_bridge" \
  --region us-central1 --project foreman-hackathon \
  --account "$ACCOUNT" \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 \
  --update-env-vars "$ENV"

gcloud run services describe foreman-glass --region us-central1 \
  --project foreman-hackathon --account "$ACCOUNT" \
  --format='value(status.latestReadyRevisionName, status.url)'
