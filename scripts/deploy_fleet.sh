#!/usr/bin/env bash
# Deploy the 3-agent fleet (foreman_app/) as Cloud Run service `foreman-hello`
# — the ADK API server the intake paths POST /run to.
#
# Two flags are load-bearing and were silently lost in a manual redeploy on
# 2026-08-20 (sessions fell back to in-memory; caught 2026-08-25 by the
# sessions table not growing):
#   --session_service_uri  → DatabaseSessionService on Cloud SQL (durable sessions)
#   --otel_to_cloud        → Cloud Trace/Logging/Monitoring waterfall
# Env vars (GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_LOCATION=global,
# FOREMAN_DB_URL, GOOGLE_CLOUD_PROJECT) are inherited from the live revision;
# pass FOREMAN_SESSION_URI (sqlalchemy+asyncpg DSN over the Cloud SQL socket):
#   postgresql+asyncpg://postgres:<pw>@/foreman?host=/cloudsql/foreman-hackathon:us-central1:foreman-pg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${FOREMAN_SESSION_URI:?set FOREMAN_SESSION_URI (see header)}"
export CLOUDSDK_CORE_ACCOUNT="${DEPLOY_ACCOUNT:-foreman-agent@foreman-hackathon.iam.gserviceaccount.com}"

"$ROOT/.venv/bin/adk" deploy cloud_run \
  --project=foreman-hackathon --region=us-central1 \
  --service_name=foreman-hello --app_name=foreman_app \
  --otel_to_cloud \
  --session_service_uri="$FOREMAN_SESSION_URI" \
  "$ROOT/foreman_app" \
  -- --no-allow-unauthenticated --max-instances=1 \
     --add-cloudsql-instances=foreman-hackathon:us-central1:foreman-pg

# adk deploy exits 0 even when the deploy failed — read the truth from Cloud Run.
gcloud run services describe foreman-hello --region us-central1 \
  --project foreman-hackathon \
  --format='value(status.latestReadyRevisionName, status.latestCreatedRevisionName, status.url)'
