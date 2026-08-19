# Cloud Run Cheatsheet — Foreman+ (foreman-hackathon project, us-central1)

Verified live 2026-08-19: `gcloud --version` = Google Cloud SDK **561.0.0**. Our live service
`foreman-hello` inspected directly (see bottom). Sources: [gcloud run deploy ref](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy),
[traffic migration](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration),
[Cloud SQL connect](https://docs.cloud.google.com/sql/docs/postgres/connect-run),
[service-to-service auth](https://docs.cloud.google.com/run/docs/authenticating/service-to-service),
[pricing](https://cloud.google.com/run/pricing), live `gcloud run deploy --help` + `adk deploy cloud_run --help`.

## 1. Deploy: source vs image

```bash
# From source (Buildpacks/Dockerfile auto-detected, builds via Cloud Build) — what `adk deploy cloud_run` uses under the hood
gcloud run deploy SERVICE --source=. --region=us-central1 --project=foreman-hackathon

# From a pre-built image (Artifact Registry / any registry Cloud Run can pull)
gcloud run deploy SERVICE --image=us-docker.pkg.dev/PROJECT/REPO/IMAGE:TAG --region=us-central1
```
- `--source` triggers a Cloud Build job (needs `roles/cloudbuild.builds.builder` on the **compute default SA**, confirmed gotcha for fresh projects — matches our project CLAUDE.md note).
- `adk deploy cloud_run <agent_dir>` generates a temp source dir (Dockerfile + main.py wrapping the ADK API server) and internally calls `gcloud run deploy --source=<temp_dir>`. **UNVERIFIED beyond CLI --help**: exact generated Dockerfile contents — read `~/Projects/.../adk/cli/cli_deploy.py` source if a build breaks (per our own gotcha: default Dockerfile lacks `[db]` extra → drop a `requirements.txt` in the agent dir to override).
- `adk deploy cloud_run --help` (installed 2.7.1, verified live) key flags: `--project`, `--region` (both effectively required), `--service_name` (default `adk-default-service-name`), `--app_name`, `--port` (default 8000), `--with_ui` (dev/test only, NOT for prod judges), `--adk_version` (defaults to installed = 2.7.1), `--a2a`, `--trigger_sources=pubsub,eventarc`, `--allow_origins`. Use `--` to pass raw `gcloud run deploy` flags after it, e.g.:
  ```bash
  adk deploy cloud_run --project=foreman-hackathon --region=us-central1 agents/foreman \
    -- --no-allow-unauthenticated --min-instances=0 --add-cloudsql-instances=foreman-hackathon:us-central1:foreman-pg
  ```
- 🔴 **Our own confirmed gotcha (keep):** `adk deploy` can **exit 0 on a failed deploy** — always verify with `gcloud run services describe` / `gcloud run revisions list` after, don't trust exit code alone (matches rule 02 "verify deploy took effect").

## 2. Revisions & traffic — does a failed revision keep the old one serving?

**YES — confirmed by docs.** A new revision only receives traffic once it passes health checks; if it fails to become "Ready", Cloud Run **does not shift traffic to it** and the previously-serving revision keeps serving 100%. `gcloud run deploy` by default sends 100% traffic to the new revision **only after it's healthy** (this is the "automatic" rollout mode — no manual promotion step needed, unlike GKE canary flows).
- Traffic changes are **not instantaneous** — in-flight requests finish on whichever revision they started on.
- **Gradual/canary rollout** (deploy without shifting traffic, then split manually):
  ```bash
  gcloud run deploy SERVICE --image=... --no-traffic --tag=candidate   # deploy, 0% traffic, reachable at candidate---SERVICE-xxx.run.app
  gcloud run services update-traffic SERVICE --to-tags=candidate=10    # send 10% to it
  gcloud run services update-traffic SERVICE --to-latest               # 100% to latest revision
  ```
- **Rollback** to a specific prior revision:
  ```bash
  gcloud run services update-traffic SERVICE --to-revisions=REVISION_NAME=100
  ```
- List revisions: `gcloud run revisions list --service=SERVICE --region=us-central1`.

## 3. `--add-cloudsql-instances` — unix socket mechanics (confirmed live on our own service)

- Flag appends a Cloud SQL instance connection; Cloud Run auto-mounts a Unix socket at:
  **`/cloudsql/PROJECT:REGION:INSTANCE`** — Postgres specifically listens at `/cloudsql/INSTANCE_CONNECTION_NAME/.s.PGSQL.5432`.
- **No sidecar/proxy container needed** — the Cloud SQL Auth Proxy is built into the Cloud Run runtime when this flag is set; connection is auto-encrypted.
- Required IAM: the **Cloud Run runtime service account** needs `roles/cloudsql.client`.
- **Live confirmation from our own `foreman-hello` service** (`gcloud run services describe`):
  ```yaml
  annotations:
    run.googleapis.com/cloudsql-instances: foreman-hackathon:us-central1:foreman-pg
  env:
    FOREMAN_DB_URL: postgresql://postgres:PASSWORD@/foreman?host=/cloudsql/foreman-hackathon:us-central1:foreman-pg
  ```
  For asyncpg specifically, DSN form (no host/port, `host=` query param points at the socket DIR, not the `.s.PGSQL.5432` file — asyncpg appends that itself): `postgresql://USER:PASS@/DBNAME?host=/cloudsql/CONN_NAME`.
- Add/update on an existing service: `gcloud run services update SERVICE --add-cloudsql-instances=CONN_NAME` (additive — use `--set-cloudsql-instances` to replace the whole list, `--clear-cloudsql-instances` to remove all).

## 4. Env vars — REPLACE vs MERGE semantics (verified from official flag docs — matches project CLAUDE.md warning)

| Flag | Behavior |
|---|---|
| `--set-env-vars=K=V,...` | 🔴 **REPLACES the entire env var map** — "All existing environment variables will be removed first." Never use this for a one-off update unless you pass the FULL set. |
| `--update-env-vars=K=V,...` | Merges — adds new / overwrites named keys, leaves everything else untouched. **This is what you want for incremental changes.** |
| `--remove-env-vars=K,...` | Removes only the named keys. |
| `--clear-env-vars` | Removes ALL env vars. |
| `--env-vars-file=FILE` | Set from a YAML file (also replaces, like `--set-env-vars`, unless combined semantics differ — verify before relying; **UNVERIFIED** interaction with `--update-env-vars` in same call). |

Secrets: same pattern exists for Secret Manager refs — `--set-secrets` / `--update-secrets` / `--remove-secrets` / `--clear-secrets` (mount as env var or volume, referencing `SECRET:VERSION`).

## 5. Scaling, concurrency, cold start

- `--min-instances=N` — keep N warm (avoids cold start, **costs money even idle** — see pricing). `default`/unset = 0 (scale-to-zero).
- `--max-instances=N` — hard cap per revision (immutable per revision once deployed — a new revision can set a different value). **Our live service has `maxScale: '1'`** — fine for demo/dev, but a judge triggering 2 concurrent requests will queue/reject the 2nd; bump before the judging window if concurrent access is expected.
- `--concurrency=N` — max simultaneous requests per container instance; unset/`default` = server default (**Cloud Run default is 80** per Google's stated platform default — verify per current docs if precision matters; our fetch did not return the literal number, treat as **UNVERIFIED exact value**, but 80 is the long-standing documented default).
- `--cpu=1|2|4|6|8` (fractional `<1` allowed only with concurrency=1 and no CPU boost) and `--memory=512Mi|1Gi|4Gi|...` — some CPU tiers require a memory minimum (e.g. 4 vCPU needs ≥2Gi). `--cpu-boost` gives extra CPU during cold start only (visible as `startup-cpu-boost: 'true'` on our live service).
- `--execution-environment=gen1|gen2` — gen2 (default for newer services) has full Linux syscall support (needed if any native/subprocess deps); gen1 has faster cold starts for pure HTTP workloads. **UNVERIFIED which is default for new services created via `adk deploy` today** — check `gcloud run services describe SERVICE --format='value(spec.template.metadata.annotations."run.googleapis.com/execution-environment")'` if it matters.
- Cold start: scale-to-zero (`min-instances=0`) means the FIRST request after idle pays full container-start latency (Python/ADK: expect low-single-digit seconds typically; not independently benchmarked here — **UNVERIFIED number**, budget for it in the demo video/live judging by pre-warming (hit the URL once before judges connect) or setting `--min-instances=1` for the judging window.

## 6. Request timeout

- `--timeout=SECONDS` (or duration string `1m20s`) — default **300s (5 min)**, max **3600s (60 min)**. Beyond timeout → connection closed, client sees **HTTP 504**.
  ```bash
  gcloud run services update SERVICE --timeout=1800   # 30 min
  ```

## 7. Making it viewable by judges — auth tradeoffs

| Option | Command | Tradeoff |
|---|---|---|
| **Public (simplest for a demo URL)** | `gcloud run deploy SERVICE --allow-unauthenticated` (or `gcloud run services add-iam-policy-binding SERVICE --member=allUsers --role=roles/run.invoker`) | Anyone with the URL can call it — fine for a hackathon demo API, NOT fine if it holds real secrets/spends real $$ per call uncontrolled. |
| **Authenticated + share an identity token** | Deploy with `--no-allow-unauthenticated`; judge needs a token you generate for them | Judges can't self-serve; token expires ~1hr — bad for async judging windows. |
| **Simple app-level API key gate on a public service** | Keep `--allow-unauthenticated`, but check a custom header/query param (`X-Demo-Key`) in app code before doing real work | Best of both — public URL judges can hit directly, cheap gate against random bots hammering it. **Recommended for this hackathon**: public Cloud Run + lightweight app-level key check, NOT IAM-gated (IAM-gated means judges need a GCP identity, which they won't have). |

- Service-to-service (agent → agent, or our own script → Cloud Run) using IAM auth:
  ```bash
  # Grant invoker to the calling identity
  gcloud run services add-iam-policy-binding RECEIVING_SERVICE \
    --member='serviceAccount:CALLER_SA_EMAIL' --role='roles/run.invoker' --region=us-central1

  # Get + use an identity token (local dev / human)
  ID_TOKEN=$(gcloud auth print-identity-token --audiences=https://SERVICE-URL)
  curl -H "Authorization: Bearer $ID_TOKEN" https://SERVICE-URL/endpoint
  ```
  From code (works both on/off GCP): `google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), audience=SERVICE_URL)`, header `Authorization: Bearer <id_token>` (alt header `X-Serverless-Authorization` if `Authorization` is used for something else, e.g. your own app auth). ID tokens expire ~1 hour.

## 8. Logs & metrics

```bash
# Tail logs (last N, follow not native to this cmd — use --limit + repeat, or Cloud Logging)
gcloud run services logs read SERVICE --region=us-central1 --limit=50

# Structured query via Cloud Logging (more powerful, filterable)
gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=SERVICE' \
  --project=foreman-hackathon --limit=50 --format=json

# Metrics: request count, latency, container instance count, CPU/mem utilization — via Cloud Monitoring
gcloud monitoring time-series list --filter='metric.type="run.googleapis.com/request_count"' ...
# or simpler: open the Cloud Run console service page → METRICS tab
```
Describe current state: `gcloud run services describe SERVICE --region=us-central1` (shows traffic split, revision, env, Cloud SQL annotation, URL — this is how the live values in §3 were confirmed).

## 9. Pricing & free tier (verified via search against current GCP pricing pages, Aug 2026)

**Tier 1 regions** (includes `us-central1`, our region):
- **Free tier, per month, per billing account:** 180,000 vCPU-seconds, 360,000 GiB-seconds (memory), 2,000,000 requests, **1 GiB network egress from North America** (Premium tier).
- **Beyond free tier:** ~$0.000024/vCPU-second, ~$0.0000025/GiB-second, $0.40 per million requests.
- Tier 2 regions cost more (~$0.0000336/vCPU-sec, ~$0.0000035/GiB-sec) — stay in `us-central1` (Tier 1) for cost.
- No charge for Cloud Run → Cloud Run (or other GCP resource) traffic within the same region.
- **New customers:** $300 free credit for first 90 days (separate from the hackathon's own $150 GCP promo credit — see project CLAUDE.md, redeem before 2026-09-03).

**Scale-to-zero cost behavior:**
- `min-instances=0` (default): **$0 while idle** — you pay only for actual request-serving CPU/memory time + request count. This is the free/cheap default; keep it unless you need zero cold-start.
- `min-instances≥1`: that many instances are **billed continuously** even with zero traffic (idle CPU is charged at a **reduced idle rate** unless CPU is always-allocated — UNVERIFIED exact idle-rate discount %, don't assume it's free). For a hackathon demo, prefer `min-instances=0` and pre-warm right before judges look, OR bump to `min-instances=1` only for the actual judging window and scale back down after.
- Cloud SQL (Postgres instance `foreman-pg`) bills **separately and continuously** regardless of Cloud Run traffic — that's the dominant idle cost in our stack, not Cloud Run itself. UNVERIFIED here — check Cloud SQL pricing separately if idle-cost budgeting matters.

## 10. Confirmed live state of our own service (ground truth, 2026-08-19)

```
$ gcloud run services list --project foreman-hackathon --region us-central1
SERVICE        REGION       URL
foreman-hello  us-central1  https://foreman-hello-112293816563.us-central1.run.app

# gcloud run services describe foreman-hello --region us-central1:
maxScale: '1'                      # 🔴 bump before demo if concurrent judge hits expected
run.googleapis.com/cloudsql-instances: foreman-hackathon:us-central1:foreman-pg
startup-cpu-boost: 'true'
env:
  GOOGLE_API_KEY: AQ.Ab8R...       # bound-to-SA key format, restricted to Gemini API surface
  GOOGLE_GENAI_USE_VERTEXAI: 'FALSE'
  GOOGLE_CLOUD_LOCATION: global
  FOREMAN_DB_URL: postgresql://postgres:***@/foreman?host=/cloudsql/foreman-hackathon:us-central1:foreman-pg
traffic: 100% -> revisionName foreman-hello-00007-p6d (latestRevision: true)
url (revision-specific): https://foreman-hello-gatyjfeu5q-uc.a.run.app
```
Note: two URLs exist — the stable service URL (`.../foreman-hello-112.../us-central1.run.app`) always points at whatever revision currently has traffic; the revision-tagged URL (`.../foreman-hello-gatyjfeu5q-uc.a.run.app`) is pinned to one specific revision. **Use the stable service URL for judges/demo links**, not the revision URL.

## Open / UNVERIFIED (flag before relying on in the demo)
- Exact default `--concurrency` value (treated as 80, long-standing Google default, not reconfirmed in this pass's fetches).
- Cold-start latency number for our specific ADK+gemini container.
- Default `--execution-environment` (gen1 vs gen2) for services created via `adk deploy cloud_run` today.
- Idle-rate discount % for `min-instances≥1` without always-on CPU.
- Cloud SQL instance's own idle/continuous cost (separate line item from Cloud Run).
