# Firestore (Native mode) — cheatsheet for Foreman+

Second GCP service (after Cloud Run + Cloud SQL Postgres). Verified live 2026-08-19 against
official docs. Client-library version cross-checked against PyPI (not yet installed in `.venv` —
`google-cloud-firestore` is absent from current `pip show` / site-packages; only `google-cloud-spanner`,
`google-cloud-monitoring`, `google-genai`, `google-adk 2.7.1` are installed).

Sources: firebase.google.com/docs/firestore/{quickstart,quotas,understand-reads-writes-scale,query-data/indexing},
docs.cloud.google.com/{sdk/gcloud/reference/firestore/databases/create, python/docs/reference/firestore/latest,
firestore/docs/query-data/index-overview, docs/authentication/application-default-credentials},
pypi.org/project/google-cloud-firestore, firebase.google.com/pricing.

---

## 1. Install

```bash
pip install google-cloud-firestore   # PyPI: 2.28.1, released 2026-08-06, requires Python >=3.10
                                       # (3.14 in our venv is supported: 3.10-3.14 listed)
```
Not in `requirements.txt` yet for `foreman-hello` — add it before wiring Firestore into the Cloud Run
service, same lesson as the ADK `[db]` extra gotcha (default Dockerfile misses it if unlisted).

## 2. Create the database (do this ONCE per project)

```bash
# Native mode, default database id "(default)", multi-region nam5:
gcloud firestore databases create --location=nam5

# Explicit database id + type (you can have MULTIPLE named databases per project):
gcloud firestore databases create --database=foo --location=nam5 --type=firestore-native

# For us — pick a single-region location matching Cloud Run us-central1 for lowest latency,
# e.g. --location=us-central1 (single-region) or nam5 (multi-region, US).
```
Flags (source: `docs.cloud.google.com/sdk/gcloud/reference/firestore/databases/create`):
- `--location=LOCATION` — required, list at cloud.google.com/firestore/docs/locations.
- `--type=firestore-native` — default value, explicit for clarity (vs `datastore-mode`).
- `--database=DATABASE` — omit → uses id `(default)`.

Console path (firebase.google.com/docs/firestore/quickstart): Firebase console → **Databases &
Storage → Firestore → Create database** → pick location → pick Security Rules starting mode
(test = open, production = locked down) → Create. **UNVERIFIED**: exact CLI defaults if you skip
`--type`/`--database` entirely beyond what's stated above (page content was partial).

## 3. Python client — Sync vs Async

Package: `google-cloud-firestore` (PyPI 2.28.1). Classes (docs.cloud.google.com/python/docs/reference/firestore/latest):
- `google.cloud.firestore_v1.client.Client` — sync
- `google.cloud.firestore_v1.async_client.AsyncClient` — **use this one**, our stack is asyncpg/async-first

```python
from google.cloud import firestore

# Sync
db = firestore.Client(project="foreman-hackathon", database="(default)")

# Async — this is what we use (matches asyncpg pattern elsewhere in the codebase)
from google.cloud.firestore_v1.async_client import AsyncClient
db = AsyncClient(project="foreman-hackathon", database="(default)")
# or, if only using the default DB:
# db = firestore.AsyncClient(project="foreman-hackathon")
```
`database=` param lets you target a non-default named database — relevant if we ever split
dashboard-state vs intake-queue into separate Firestore databases in the same project.

**UNVERIFIED — exact async CRUD code samples** (PyPI page and the reference-overview page did not
render full method-level code in this fetch). Below is the documented async API shape from the
library's own class references — verify signatures against installed package once
`pip install google-cloud-firestore` is run in `.venv` (`python -c "from google.cloud.firestore_v1.async_client import AsyncClient; help(AsyncClient)"`).

```python
# CRUD (async) — standard google-cloud-firestore async surface
doc_ref = db.collection("devices").document("device-123")
await doc_ref.set({"status": "online", "last_seen": firestore.SERVER_TIMESTAMP})
snap = await doc_ref.get()
data = snap.to_dict()
await doc_ref.update({"status": "offline"})
await doc_ref.delete()

# Auto-ID add
new_ref = await db.collection("intake_queue").add({"photo_url": "...", "created_at": firestore.SERVER_TIMESTAMP})

# Query
q = db.collection("devices").where("status", "==", "online")
async for doc in q.stream():
    print(doc.id, doc.to_dict())

# Listeners (on_snapshot) — NOTE: real-time listeners in the async client are less commonly used;
# the canonical `on_snapshot()` callback API is documented primarily on the SYNC client
# (Watch/threaded callback model). For an async service (Cloud Run request-response, no persistent
# connection guaranteed), prefer POLLING via `.stream()` or Firestore's REST/gRPC watch only if you
# keep a long-lived process. UNVERIFIED whether AsyncClient.on_snapshot() exists as a coroutine-native
# API in 2.28.1 — check `dir(AsyncQuery)` / `dir(AsyncDocumentReference)` after install.
```

## 4. Auth — Cloud Run vs local vs our Gemini API key

Source: `docs.cloud.google.com/docs/authentication/application-default-credentials`.

- **Cloud Run (prod):** Application Default Credentials (ADC) auto-resolves to the **attached
  service account** via the metadata server — "the preferred method... in a production environment
  on Google Cloud." **No key file, no env var needed** if the Cloud Run service's runtime SA has the
  right IAM role (`roles/datastore.user` — standard Firestore/Datastore access role; grant it to
  whatever SA `foreman-hello` runs as, likely the compute default SA already used for Cloud Build).
- **Local dev:** `gcloud auth application-default login` → writes a JSON cred file to
  `~/.config/gcloud/application_default_credentials.json` (macOS/Linux) → `AsyncClient()` picks it
  up automatically, no code changes needed between local and Cloud Run.
- **🔴 Our `AQ.` Gemini API key does NOT work here.** The ADC doc explicitly does not include API
  keys among its three credential sources (`GOOGLE_APPLICATION_CREDENTIALS` env var, gcloud ADC
  file, attached SA) — google-cloud client libraries (Firestore, Cloud SQL connector, etc.)
  authenticate via **OAuth2 service-account credentials**, not API keys. This is the opposite of the
  Gemini API surface, where the `AQ.` key IS the auth. Confirmed pattern from our own ADK gotcha
  (`AQ.` key auto-routes to Vertex inside GCP unless pinned `vertexai=False`) — Firestore has no
  equivalent API-key path at all; don't try.
- IAM role to grant explicitly if not already present:
  ```bash
  gcloud projects add-iam-policy-binding foreman-hackathon \
    --member="serviceAccount:<RUNTIME_SA>@foreman-hackathon.iam.gserviceaccount.com" \
    --role="roles/datastore.user"
  ```
  (`roles/datastore.user` covers Firestore Native mode too — Firestore and Datastore share the IAM
  role namespace historically; this is the standard grant used in official samples. Same
  `compute.builds.builder`-style gotcha pattern we hit with Cloud Build — **verify by testing a
  live read/write from the deployed Cloud Run revision**, don't assume the role is already there.)

## 5. Free tier (verified live, firebase.google.com/docs/firestore/quotas + firebase.google.com/pricing)

| Resource | Free / day |
|---|---|
| Document reads | 50,000/day |
| Document writes | 20,000/day |
| Document deletes | 20,000/day |
| Stored data | 1 GiB total |
| Outbound network | 10 GiB/month |
| Max document size | 1 MiB (1,048,576 bytes) |

Excluded from free tier even under the daily caps: TTL deletes, point-in-time recovery data,
backups/restores.

**Beyond free tier — UNVERIFIED exact per-100k $ rate.** `cloud.google.com/firestore/pricing` and
`firebase.google.com/pricing` both returned truncated content on live fetch (2026-08-19); the
Blaze-plan page confirms the same daily no-cost thresholds above and says paid usage "then Google
Cloud [Standard/Enterprise edition] pricing applies" without rendering the per-unit table in this
session. Historical published rates (do NOT cite these to judges without re-verifying at build
time) were roughly $0.036/100k reads, $0.108/100k writes, $0.012/100k deletes, $0.18/GiB-month
storage in `nam5`/`us-central1` — **re-fetch `cloud.google.com/firestore/pricing` directly in a
browser before relying on any $ figure.**

## 6. Indexes — gotchas (verified live)

- **Single-field indexes are automatic** — "indexes required for the most basic queries are
  automatically created for you." No action needed for simple equality/single-field queries.
- **Composite (manual) indexes required** for compound queries with a **range clause** that doesn't
  map to an existing index (e.g. `where("status","==","open").where("created_at",">",x)` combined
  with an `order_by` on a third field, or multiple inequality filters). Attempting one without the
  index → the query **fails at call time** with an error.
- **The error is self-service:** Firestore's error message includes a **direct link to create the
  missing index in the Firebase console**, pre-populated with the right field/order config — click
  it, wait ~1-5 min for the index to build, retry. This is the normal dev-loop, not a design flaw —
  budget for it (don't discover this during the live demo; pre-run every query shape you'll use in
  the video against staging first).
- Vector-index errors (if we ever store embeddings in Firestore instead of pgvector) surface a
  **gcloud CLI command** instead of a console link — different UX, note if it comes up.

## 7. 1-write/sec-per-document — status: **could not confirm as a current hard limit**

The classic "Firestore documents are limited to 1 sustained write per second" guidance (heavily
cited around the web, incl. our own task brief) was **NOT found stated on either
`firebase.google.com/docs/firestore/quotas`** (no per-second throughput ceiling mentioned there —
only daily quotas + 10 MiB max request size + 270s transaction limit + 500 field-transforms/commit)
**nor on `understand-reads-writes-scale`** (that page discusses transaction/split latency growing
with participant count, not a hard 1/sec cap). **Mark UNVERIFIED as a hard documented limit in
2026** — it may have been relaxed/superseded, or it may still apply as informal guidance not
surfaced on these two pages. **Design implication either way: don't hot-loop writes to a single
doc** (e.g. one shared "fleet status" doc updated by every agent tick) — shard into
per-entity docs (`devices/{id}`, `jobs/{id}`) rather than one aggregate doc, which is the correct
Firestore pattern regardless of the exact throttle number.

## 8. Where Firestore fits vs our Postgres (design call for Foreman+)

| Data | Store | Why |
|---|---|---|
| Bi-temporal facts, write-gate journal | **Postgres** (Cloud SQL, asyncpg) | already relational, needs joins/temporal queries, ACID across our own tables |
| ADK session state | **Postgres** (`DatabaseSessionService`) | already decided, same DB as facts |
| **Live dashboard state** (React Flow node positions/status pushed to browser) | **Firestore** | its `on_snapshot`/real-time listener model is built exactly for "push UI state to a connected client with zero extra infra" — Postgres would need LISTEN/NOTIFY + a websocket layer we'd build ourselves |
| **Device intake queue** (photo/voice capture events waiting for an agent to pick up) | **Firestore** (or Pub/Sub) | write-heavy, loosely-structured, short-lived docs; free tier (20k writes/day) likely covers hackathon demo volume; simple `.add()` from any capture device with no server round-trip if we ever go client-direct |
| **Session flags** (ephemeral UI/agent coordination flags, not the durable session state) | **Firestore** — lightweight, no schema migration needed | keep the *durable* session state in Postgres per current design; Firestore only for the parts that benefit from real-time push |

Net: Firestore's value-add for us is **real-time push to the dashboard + a 2nd required GCP
service** for the judging rubric — not a replacement for Postgres. Keep write-gate/bi-temporal
facts in Postgres; use Firestore for anything the browser needs to see update live without polling.

## 9. Open items to verify before relying on this in the submission

- [ ] Actually `pip install google-cloud-firestore` in `.venv`, `import`, confirm `AsyncClient`
      method names against source (`site-packages/google/cloud/firestore_v1/async_client.py`,
      `async_query.py`, `async_document.py`) — this doc's CRUD/listener code is from docs, not from
      the installed package (package wasn't installed at cheatsheet-writing time).
- [ ] Re-fetch `cloud.google.com/firestore/pricing` directly (not via WebFetch summarizer) for the
      real per-100k $ figures before quoting any cost number to judges or in the README.
- [ ] Confirm `roles/datastore.user` is sufic ent for our Cloud Run SA by testing a live write from
      a deployed revision, not by IAM-doc inference alone (rule: verify from ground truth).
- [ ] Confirm/deny the 1-write/sec-per-document limit's current status (§7) if we ever put
      high-frequency writes on a single doc — right now our design already shards per-entity, so
      this is low-risk, but don't build a shared aggregate-status doc without re-checking.
