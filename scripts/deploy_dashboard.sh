#!/usr/bin/env bash
# Deploy the read-only ops dashboard (foreman-dash) to Cloud Run.
#
# Vendors foreman_app/foreman_core into dashboard/ first: the dashboard ships
# as its own buildpack context, and the /doc closeout renders import
# foreman_core directly. The vendored copy is gitignored — this script is the
# only thing that produces it.
#
# FOREMAN_DB_URL / GOOGLE_CLOUD_PROJECT persist from the previous revision (this
# script never carries secrets). The Vertex switch is set explicitly on every
# deploy because a 20.08 redeploy silently dropped it and recall went dark.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT="${DEPLOY_ACCOUNT:-foreman-agent@foreman-hackathon.iam.gserviceaccount.com}"

rsync -a --delete --exclude '__pycache__' \
  "$ROOT/foreman_app/foreman_core/" "$ROOT/dashboard/foreman_core/"

gcloud run deploy foreman-dash \
  --source "$ROOT/dashboard" \
  --region us-central1 --project foreman-hackathon \
  --account "$ACCOUNT" \
  --allow-unauthenticated \
  --add-cloudsql-instances foreman-hackathon:us-central1:foreman-pg \
  --update-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global \
  --max-instances 1

# adk/gcloud can exit 0 on a failed rollout — verify the serving revision
gcloud run services describe foreman-dash --region us-central1 \
  --project foreman-hackathon --account "$ACCOUNT" \
  --format='value(status.latestReadyRevisionName, status.url)'
