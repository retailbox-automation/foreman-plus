# Foreman+

**A gated shared memory for a field-service agent fleet — every fact a technician reports is verified before it becomes truth, and the record outlives the visit.**

![Google ADK](https://img.shields.io/badge/Google-ADK%202.7-4285F4?logo=google)
![Gemini 3.7 Flash](https://img.shields.io/badge/Gemini-3.7%20Flash%20on%20Vertex%20AI-8E44AD)
![Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-4285F4?logo=googlecloud)
![Cloud SQL](https://img.shields.io/badge/Cloud%20SQL-Postgres%20%2B%20pgvector-336791?logo=postgresql)
![Firestore](https://img.shields.io/badge/Firestore-native%20mode-FFA000?logo=firebase)
![A2A](https://img.shields.io/badge/Protocol-A2A-0F9D58)
![MIT](https://img.shields.io/badge/license-MIT-informational)

---

## What it does

A field technician photographs the equipment nameplate and talks. Foreman+ turns that into a
verified job record in about 15 seconds: a price the technician can quote before leaving the
driveway, every number traceable back to "where did this come from," and the next person on the
job — a comfort advisor, a callback tech, a home-warranty authorizer — arrives with the property's
memory instead of starting from zero.

Three things make that work:

- **Capture at zero cost, with an honest UNKNOWN.** The intake agent reads a photo of the nameplate
  and a spoken description directly through the ADK `Runner` — the model pulls the equipment model
  and serial number out of the *image*, never out of the technician's words. When the plate is
  unreadable, the field stays `UNKNOWN` rather than getting silently guessed; a voice follow-up can
  fill it in later, tagged with where the value came from.
- **One record, two audiences.** The same gate-verified facts render two ways: a technician-facing
  stamp that survives a later dispute, and a homeowner-facing document that puts the real number in
  front of the right person — "$4k" and "$223" for the same nameplate read very differently, and the
  document shows exactly which facts and flags produced each one.
- **Property memory outlives the visit and the person.** Every fact — approved *and* rejected — sits
  in one shared store the whole fleet reads. The closer agent briefs whoever shows up next from that
  memory: what's verified, what was rejected and why, and what similar jobs the fleet has seen before.

## Why the write-gate matters

Nothing reaches shared memory by just being said. Every proposed fact goes through one path:

```
Proposal → journal opened → cheap guards → per-(subject,predicate) DB lock →
LLM verify against existing facts → apply (fact write + journal close, one transaction)
```

- **Cheap guards run before any billed LLM call**: the proposing agent must be a registered fleet
  member, the value must fit a 4096-byte cap, and a subject can't exceed 64 predicates — garbage
  never reaches the verifier.
- **The verifier judges against what's already known**, not in a vacuum. It's given the proposal and
  the subject's existing facts explicitly labeled as *data to judge, never instructions* — a proposal
  or an existing fact that tries to talk to the verifier ("approve this," "system note: pre-verified")
  is itself grounds for rejection. This is the write path's defense against prompt injection.
- **Verifier failure fails CLOSED.** If the judge call errors or comes back empty, the write is
  rejected — a broken verifier can never silently admit an unverified fact.
- **Rejections are never deleted — they're kept in the gate journal with their reason**, and the
  closer's closeout document lists them explicitly so nothing looks silently dropped. Concrete
  example from the test suite: a customer says the water heater is *"a couple of years old"*; the
  nameplate says `manufacture_date: 05/2004`. The verifier rejects the newer claim — *"contradicts
  plate date 05/2004; source is an unverified verbal claim"* — and the closeout document shows the
  nameplate date, not the guess.
- Every gate call carries an OpenTelemetry span (`write_gate.submit`) that nests under ADK's own
  agent/tool spans, so one Cloud Trace waterfall reads intake → LLM → gate → database for a single
  request.

## Architecture

![Foreman+ architecture](docs/architecture/foreman-architecture.svg)

Three ADK agents share one gated Postgres memory store and are deployed as independent services:

- **`foreman`** is the entry point. On a new job it records every reported attribute (equipment
  model, serial number, manufacture date, refrigerant, issue) into shared memory, then uses ADK's
  native `sub_agents` transfer to hand off — to `estimator` for scoping, or to `closer` for
  close-out/briefing.
- **`estimator`** reads the job's current facts and searches the whole fleet's memory for similar
  past equipment/issues before producing a one-line JSON estimate, which it writes back to memory
  itself.
- **`closer`** never writes memory — it only reads it. It builds the deterministic closeout document
  (no LLM call in that path) and briefs the next human from the same shared facts. It's the only
  agent exposed outside the fleet, over **A2A**, as its own Cloud Run service — the fleet's
  CRM-agnostic exit for a downstream FSM, a home-warranty authorizer, or another agent fleet
  entirely.
- The **write-gate** (above) sits between every agent and Postgres. Approved writes are also
  published, best-effort, to a Firestore `activity` collection that feeds the live dashboard —
  Postgres stays the single system of record regardless of whether that publish succeeds.
- The **dashboard** is a fourth, separate Cloud Run service: a read-only FastAPI app with no LLM
  calls and no write path, safe to expose publicly. It aggregates Postgres + Firestore into one
  `/api/state` payload for the control-room UI, and serves the closeout document directly
  (`/doc/{job_id}`, `/api/closeout/{job_id}`) by reading the same deterministic builder the closer
  agent uses.
- The dashboard doesn't import the core package over the network — at deploy time
  `scripts/deploy_dashboard.sh` vendors `foreman_app/foreman_core/` into `dashboard/` (rsync, then
  `gcloud run deploy`), so the dashboard ships as its own self-contained build context.

## Live demo

- **Dashboard (public, read-only):** https://foreman-dash-112293816563.us-central1.run.app
  — fleet topology, the gate journal (every approve/reject with the verifier's reason), the job
  board, and a live activity feed.
- **Closeout document example:** https://foreman-dash-112293816563.us-central1.run.app/doc/J-VRTX1
  (add `?mode=decider` for the absent-decision-maker version of the same job).
- **Closer agent card (A2A discovery):**
  https://foreman-closer-112293816563.us-central1.run.app/.well-known/agent-card.json
  — publicly readable, no auth required. Try discovery yourself:

  ```bash
  curl https://foreman-closer-112293816563.us-central1.run.app/.well-known/agent-card.json
  ```

  The RPC skills behind it (`close_out_job`, `lookup_facts`, `recall_similar`) require an
  `X-Foreman-Key` header — a public Cloud Run URL must not be a free-to-call LLM endpoint,
  so unauthenticated RPC returns 401. The key is shared with judges separately in the
  submission's testing instructions, not in this file.

## Hands-free capture: smart glasses (device-agnostic intake)

The intake path takes **a photo + spoken notes as plain files** — it doesn't know or care what
captured them. A phone works today; the same path is wired to **Mentra Live camera glasses**
(camera + mic + speaker, no display) so a technician can file a job without taking their hands off
the equipment, and it is ready for the Android XR glasses shipping this fall.

Two small services extend the fleet for the glasses leg:

- **`glass_bridge/`** — `foreman-glass` (Cloud Run, Bun + `@mentra/sdk`). Registered in the
  MentraOS developer console as `com.retailbox.foreman`. One press of the glasses' camera button
  takes the system photo; the bridge receives it via the `photo_taken` broadcast (a single
  shutter — it never calls `requestPhoto` on the button, which would fire a second one). Final
  transcripts accumulate as voice notes; **"send it"** POSTs photo + notes to the fleet's ADK
  `/run` endpoint with a Google ID token, and the reply is rendered deterministically into a
  spoken sentence — the gate's verdicts included: *"Logged Rheem 82V40-2, made 05/2004. Gate
  approved 4 facts. Estimate: 2 hours, parts: lower heating element and thermostat."* No JSON is
  ever read aloud.
- **`live_brain/`** — `foreman-brain` (Cloud Run, Python). A persistent **Gemini Live API**
  session on Vertex AI (`gemini-live-2.5-flash`, text-response mode) that keeps the technician's
  latest photo or video frame as its "eyes" and answers hands-free questions in one or two spoken
  sentences ("point the camera at the shutoff valve"). Verified live: 0.24–0.67 s per turn with a
  frame attached, and a 6-minute session with a frame every 2 s survives with session resumption.
  For live guidance the same brain also accepts a directory of frames from `ffmpeg` (the glasses'
  RTMP stream over LAN, or a laptop webcam for glasses-free testing).

Everything works without the glasses — they're a capture device, not a dependency.

## Google stack checklist

| Requirement | How Foreman+ uses it |
|---|---|
| **Gemini** | `gemini-3.7-flash` reasons for all three fleet agents *and* judges every write-gate proposal; **`gemini-embedding-2`** (Google's multimodal embedding model, 768 dims pinned on every call) embeds facts for semantic recall; **`gemini-live-2.5-flash` (Live API)** powers the hands-free guidance brain. All called through Vertex AI. |
| **Google Agent Framework** | Google **ADK** 2.7.1 — the 3-agent fleet with native `sub_agents` LLM-driven transfer, `DatabaseSessionService` for durable session state on Postgres, and `to_a2a()` to expose `closer` as its own A2A service. |
| **Google Cloud service** | **Cloud Run** (5 services: `foreman-hello` — the fleet's ADK API server and intake target, `foreman-dash`, `foreman-closer`, `foreman-glass`, `foreman-brain`), **Cloud SQL** (Postgres + `pgvector`, HNSW cosine index — system of record for facts and the gate journal), **Firestore** (native mode — best-effort live activity feed). |
| **Observability** | OpenTelemetry via `--otel_to_cloud` (Cloud Trace + Cloud Logging + Cloud Monitoring from one flag); the write-gate's own span nests under ADK's spans for a single per-request waterfall. |
| **Additional Google AI model** | **Veo 3.1** was used to generate the non-application video assets (b-roll/establishing shots) for the submission demo video — it is not part of the running application. |

## Run it yourself

### Prerequisites
- Python 3.14, local Postgres with the `pgvector` extension available.
- A GCP project with Vertex AI enabled and Application Default Credentials (or a service account
  key) for it.

### Env vars
```bash
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=<your-gcp-project>
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=<path to a service-account key json>
FOREMAN_DB_URL=postgresql://<user>@localhost:5432/foreman_core
# Optional, A2A card + guard (see foreman_app/a2a_app.py):
A2A_HOST=localhost
A2A_CARD_PORT=8080
A2A_PROTOCOL=http
A2A_SHARED_SECRET=<any string — enables the X-Foreman-Key guard>
```
Do not set `GEMINI_API_KEY`/`GOOGLE_API_KEY` alongside `GOOGLE_GENAI_USE_VERTEXAI=TRUE` — the two
paths conflict. No `.env.example` is committed yet; the block above is the full set this repo reads.

### Install
```bash
pip install -r foreman_app/requirements.txt
```
**Gotcha:** the `google-adk[db,gcp,otel-gcp,a2a]` extra does **not** pull in `sse-starlette`, which
the A2A app needs — it's listed explicitly in `foreman_app/requirements.txt`. If you hand-roll the
extras list, add it yourself.

### Run the fleet locally
```bash
createdb foreman_core
adk web foreman_app                       # dev UI + API, http://127.0.0.1:8000
# or headless:
adk api_server foreman_app --otel_to_cloud
```

### Run the dashboard locally
```bash
cd dashboard && pip install -r requirements.txt
FOREMAN_DB_URL=... GOOGLE_CLOUD_PROJECT=<your-gcp-project> \
  uvicorn main:app --host 0.0.0.0 --port 8080
```

### Run the A2A closer service locally
```bash
FOREMAN_DB_URL=... uvicorn foreman_app.a2a_app:a2a_app --host 0.0.0.0 --port 8080
```

### Deploy (Cloud Run)
```bash
scripts/deploy_dashboard.sh                                     # deploys foreman-dash
FOREMAN_DB_URL_PROD=<Cloud SQL socket DSN> scripts/deploy_closer_a2a.sh   # deploys foreman-closer
```
Both scripts deploy with `--add-cloudsql-instances` to a Cloud SQL Postgres instance, run as a
dedicated service account, and explicitly re-`describe` the resulting revision afterward — `gcloud`
can exit `0` on a failed rollout, so the scripts don't take that at face value.

### Tests
```bash
createdb foreman_core_test
pytest tests/ -m "not integration"        # unit-level, local Postgres, no live Gemini calls
pytest tests/ -m integration              # live Vertex AI calls (verifier, multimodal intake, e2e)
```
45 unit tests across 11 files cover the write-gate's guards and fail-closed behavior, bi-temporal
memory, semantic recall, the deterministic closeout builder, the A2A agent card, and the
dashboard's `/doc` and `/api/closeout` endpoints.

## Project structure

```
foreman_app/
  agent.py              # the 3-agent fleet: foreman, estimator, closer
  runtime.py             # lazy bootstrap: Postgres pool, write-gate, fleet registration
  a2a_app.py             # closer exposed over A2A, X-Foreman-Key guard
  foreman_core/
    memory.py            # bi-temporal MemoryStore (asyncpg + pgvector)
    gate.py               # WriteGate: propose → guard → lock → verify → apply
    verifier.py            # GeminiVerifier — the LLM judge
    embedder.py             # GeminiEmbedder — gemini-embedding-2, 768 dims
    closeout.py              # deterministic closeout builder + 3 renders
    activity.py               # best-effort Firestore live-activity feed
    genai_client.py            # Vertex AI vs. legacy Gemini key client factory
    db.py                       # pool + schema bootstrap
    schema.sql                   # agents / gate_journal / memory_facts
    tools.py                      # agent-facing tool factories
dashboard/
  main.py                # read-only ops console (FastAPI)
  static/index.html       # control-room SPA
glass_bridge/              # Mentra Live glasses → fleet intake (Bun, @mentra/sdk) → foreman-glass
  src/index.ts            # AppServer: single-shutter photo, voice commands, submit, speak-back
  src/job.ts              # in-memory job, /run payload, deterministic spoken rendering
  src/foreman.ts          # ID-token clients for the fleet and the brain
  scripts/simulate_submit.ts  # glasses-free e2e against the real Cloud Run fleet
live_brain/                # Gemini Live guidance brain (Python) → foreman-brain
  brain.py                # persistent Live session: frames + text in, reconnect/resumption
  server.py               # FastAPI: POST /frame, POST /utterance
  glasses_rig.py          # LAN rig: glasses RTMP frames + transcript → brain → ear
scripts/
  deploy_dashboard.sh     # vendors foreman_core/, deploys foreman-dash
  deploy_closer_a2a.sh     # stages foreman_app/, deploys foreman-closer
  deploy_glass_bridge.sh   # deploys foreman-glass (min-instances 1: long-lived glasses session)
  deploy_live_brain.sh     # deploys foreman-brain (auth-only, called by the bridge)
  backfill_embeddings.py   # one-off: embed pre-existing facts
docs/stack/                # verified cheat-sheets for the underlying Google stack
tests/                     # 11 files, unit + integration
```

## Honest limitations

- **`foreman-closer`'s A2A RPC requires a shared key.** The agent card is publicly discoverable
  (live, no auth), but every skill call requires the `X-Foreman-Key` header — deliberate, so the
  public URL is not a free-to-call LLM endpoint. Judges receive the key in the testing
  instructions.
- **Demo video assets used Veo's GA endpoint**, not a preview/experimental one — no preview-only
  Veo capability is part of this submission.
- **No CI pipeline.** Tests are run manually (`pytest`); there's no GitHub Actions workflow in this
  repo yet.
- **No root `.env.example` is committed.** The env var block in "Run it yourself" above is the
  authoritative list for the fleet; `glass_bridge/.env.example` covers the glasses bridge.
- **`foreman-hello` is the fleet's ADK API server** (auth-only; the name is left over from the
  first cloud spike). It is the intake target for the glasses bridge and the `/run` endpoint used
  in the demo; only its callers (Cloud Run service accounts) hold `run.invoker` on it.
- **The glasses leg runs on MentraOS's Cloud SDK, which the vendor is sunsetting** (it works in the
  "MentraOS Legacy" app through October 2026; the successor Miniapp/Bluetooth SDKs are in beta). The
  bridge is ~300 lines and the intake contract is device-agnostic, so porting is a bridge rewrite,
  not a fleet change. The glasses are also not required for anything: the phone path is primary.
- **The Live guidance brain is text-in/text-out over Gemini Live** — spoken replies go through
  MentraOS's TTS, not Gemini's native audio output. Vertex AI's `gemini-live-2.5-flash-native-audio`
  rejects text responses (error 1007, verified), and the glasses' Cloud SDK has no raw-PCM playback
  path, so native audio out is deferred to the Miniapp SDK.
- **Every Cloud Run service runs at `--max-instances 1`.** That's a deliberate choice for the
  hackathon window (predictable cost, one Cloud SQL connection budget), not a production autoscaling
  configuration.
- **The Firestore activity feed and the embedder are both best-effort.** A missing Firestore
  credential or an embedding failure never blocks a fact write — it degrades the live dashboard feed
  or semantic recall for that fact, silently, by design (wrapped in `try`/`except` at the call site).
