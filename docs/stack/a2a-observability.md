# Foreman+ Cheatsheet: A2A + Observability (ADK 2.7.1)

Verified against **installed package** at `.venv/lib/python3.14/site-packages/google/adk/` (version confirmed live: `pip show google-adk` → **2.7.1**) + live docs at `adk.dev` (the `google.github.io/adk-docs` domain 301-redirects here now) + Google Cloud docs. Anything not confirmed against one of these is marked **UNVERIFIED**.

---

## A. A2A Protocol

### A.1 — Two ways to expose an ADK agent over A2A

| Method | Where (code) | When to use |
|---|---|---|
| `to_a2a()` helper | `google/adk/a2a/utils/agent_to_a2a.py` | Simplest — wrap one agent into its own Starlette app, run with `uvicorn`. **Recommended for our multi-service split.** |
| `adk api_server --a2a` / `adk web --a2a` / `adk deploy cloud_run --a2a` | `cli_tools_click.py` (flag defined 3×: line ~1884 for `adk run`-family, ~2345 for `deploy cloud_run`, plus `adk web`) | Multi-agent hosting on one server; **requires you to hand-author `agent.json`** per agent dir (no auto agent-card generation on this path). |

`to_a2a()` signature (verified, `agent_to_a2a.py`):
```python
def to_a2a(
    agent: BaseAgent | Workflow,
    *,
    host: str = "localhost",
    port: int = 8000,
    protocol: str = "http",
    rpc_path: str = "",                 # mount prefix; "" = root
    agent_card: AgentCard | str | None = None,   # auto-built if omitted
    push_config_store: PushNotificationConfigStore | None = None,
    task_store: TaskStore | None = None,          # DatabaseTaskStore works — see A.5
    runner: Runner | None = None,
    lifespan: ... | None = None,
    agent_executor_factory: ... | None = None,
) -> Starlette
```
Example (from live docs, `adk.dev/a2a/quickstart-exposing/`):
```python
from google.adk.a2a.utils.agent_to_a2a import to_a2a

root_agent = Agent(model="gemini-flash-latest", name="hello_world_agent")
a2a_app = to_a2a(root_agent, port=8001)
# uvicorn module:a2a_app --host localhost --port 8001
```
Install extra required: **`pip install "google-adk[a2a]"`** (pulls `a2a-sdk`; not in our current `.venv` — confirmed absent, `find .../site-packages/a2a` → not found. Add before building A2A). Note: our repo's `requirements.txt` used for Cloud Run deploy needs this extra too, or the Dockerfile build will fail at import.

`@a2a_experimental` decorator is on `to_a2a()` and `AgentCardBuilder` in this version — **A2A surface is still marked experimental in 2.7.1**, expect it in release notes/breaking-change risk.

### A.2 — Endpoints created

Verified from `google/adk/a2a/_compat.py::attach_a2a_routes_to_app` (used by both the `--a2a` CLI path and internally by `to_a2a()`'s underlying route wiring) and the `adk.dev` quickstart:

- **Agent card (well-known):** `GET {base}/.well-known/agent-card.json` — auto-generated JSON (name, description, skills, capabilities) when using `to_a2a()`; hand-written `agent.json` when using `--a2a`.
  - Older a2a-sdk (0.3.x) fallback constant in our installed code: `/.well-known/agent.json` (`remote_a2a_agent.py` imports `AGENT_CARD_WELL_KNOWN_PATH` from `a2a.utils.constants`, falls back to this literal if the import fails — ADK auto-detects sdk major version, "New integrations should target 1.x.x" per docs).
- **JSON-RPC route:** mounted at `rpc_path` (default `""` = server root) for `to_a2a()`. For the CLI `--a2a` multi-agent path, each discovered agent dir gets its own prefix: **`/a2a/{app_name}`** (verified, `fast_api.py` line ~440: `_compat.attach_a2a_routes_to_app(app, ..., prefix=f"/a2a/{app_name}")`), so its card lands at `/a2a/{app_name}/.well-known/agent-card.json`.
- **CLI `--a2a` discovery mechanic (verified, `fast_api.py`):** it walks `agents_dir`, and for every subfolder containing an `agent.json` file, mounts it as an A2A agent under that prefix. **No `agent.json` in an agent's dir ⇒ silently skipped, not an error** — easy footgun, check server startup log line `"Setting up A2A agent: %s"` / `"Successfully configured A2A agent: %s"`.

### A.3 — Consuming a remote A2A agent: `RemoteA2aAgent`

Constructor (verified, `google/adk/agents/remote_a2a_agent.py`, class `RemoteA2aAgent(BaseAgent)`):
```python
RemoteA2aAgent(
    name: str,
    agent_card: AgentCard | str,        # AgentCard obj, URL, or local file path
    *,
    description: str = "",
    httpx_client: httpx.AsyncClient | None = None,   # deprecated in favor of a2a_client_factory
    timeout: float = 600.0,             # DEFAULT_TIMEOUT
    a2a_client_factory: A2AClientFactory | None = None,
    a2a_request_meta_provider: Callable[[InvocationContext, A2AMessage], dict] | None = None,
    full_history_when_stateless: bool = False,
    config: A2aRemoteAgentConfig | None = None,
    use_legacy: bool = True,            # False = new ADK↔A2A integration extension
    **kwargs,
)
```
Doc example (`adk.dev/a2a/quickstart-consuming/`):
```python
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH

prime_agent = RemoteA2aAgent(
    name="prime_agent",
    description="Agent that handles checking if numbers are prime.",
    agent_card=f"http://localhost:8001/a2a/check_prime_agent{AGENT_CARD_WELL_KNOWN_PATH}",
)
```
Then use `prime_agent` as a normal `sub_agents=[...]` entry or `AgentTool` on a parent `LlmAgent` — the parent transfers control to it exactly like a local sub-agent; ADK converts events across the A2A wire transparently (`convert_a2a_message_to_event` / `convert_event_to_a2a_message` in `a2a/converters/`).

`RemoteA2aAgent` does NOT accept auth headers directly in its public kwargs — auth goes through the injected `httpx_client` (set default headers on it) or `a2a_client_factory`'s config, or a `request_interceptors` hook on `A2aRemoteAgentConfig` (`before_request` callback gets `(InvocationContext, A2AMessage, ParametersConfig)` and can attach a `client_call_context`). **UNVERIFIED**: exact field name/shape for passing a bearer token via `ParametersConfig.client_call_context` — read `google/adk/a2a/agent/config.py` `ClientCallContext`/`_compat.ClientCallContext` before wiring; not fully traced this pass.

### A.4 — Auth between two Cloud Run services (standard GCP pattern, not ADK-specific)

Google's official docs contain **no ADK-specific A2A auth guidance** (confirmed — quickstart pages explicitly say nothing about it). Use the standard Cloud Run service-to-service pattern (verified live, `docs.cloud.google.com/run/docs/authenticating/service-to-service`):

1. Grant the **calling** service's runtime service account the invoker role on the **receiving** service:
   ```bash
   gcloud run services add-iam-policy-binding RECEIVING_SERVICE \
     --member='serviceAccount:CALLING_SERVICE_SA' \
     --role='roles/run.invoker'
   ```
2. Fetch an ID token scoped to the receiving service's URL as audience, and attach it as a Bearer token:
   ```python
   import google.auth.transport.requests
   import google.oauth2.id_token

   auth_req = google.auth.transport.requests.Request()
   id_token = google.oauth2.id_token.fetch_id_token(auth_req, audience=RECEIVING_SERVICE_URL)
   headers = {"Authorization": f"Bearer {id_token}"}
   ```
3. Wire it into `RemoteA2aAgent` via a custom `httpx.AsyncClient(headers=headers)` passed as `httpx_client=`, **or** refresh per-call inside an `A2aRemoteAgentConfig.request_interceptors` `before_request` hook (tokens expire — prefer the interceptor if calls span >1h).
4. Cloud Run alt header if `Authorization` is consumed elsewhere in your stack: `X-Serverless-Authorization: Bearer <ID_TOKEN>`.

If both agents share one Cloud Run **service** (one process), skip all of this — see A.5.

### A.5 — Is A2A meaningful WITHIN one app, or only cross-service?

**A2A is a wire protocol for crossing a process/service boundary.** Two sub-agents inside the *same* ADK app/process talk to each other for free via normal `sub_agents=[...]` / `AgentTool` composition — no A2A involved, no HTTP hop, shared in-process `InvocationContext`. Wrapping same-process agents in `RemoteA2aAgent`↔`to_a2a()` would add JSON-RPC/HTTP serialization overhead for zero benefit **unless** you specifically want:
- **independent deploy/scale lifecycles** (e.g. a heavy vision-triage agent on its own Cloud Run service+GPU/memory profile, separate from the cheap dispatcher), or
- **language/framework boundary** (agent B not built on ADK), or
- **security boundary** (agent B holds different credentials/tools you don't want in-process with agent A).

**For Foreman+: A2A is meaningful once we split the fleet across ≥2 Cloud Run services** (e.g. `foreman-intake` service ↔ `foreman-dispatch` service). Until then, keep the fleet as in-process `sub_agents`/routing inside one ADK app — simpler, no auth/network surface, same judged "modularity" credit if the code is cleanly separated into modules even without a network hop. A2A becomes a genuine architecture point (not just a checkbox) once agents are independently deployable — that's the story to tell judges: "agent boundaries chosen for independent scaling, not because A2A exists."

`A2aRemoteAgentConfig`'s `DatabaseTaskStore` (from `a2a.server.tasks`) — verified in `to_a2a()`'s docstring example — lets an A2A-exposed agent persist task state to our existing Cloud SQL Postgres instead of `InMemoryTaskStore` (which loses all task state on Cloud Run cold start/scale-to-zero). If we do split into services, use this, engine passed via `create_async_engine("postgresql+asyncpg://...")`, disposed via the app `lifespan` — matches our asyncpg-direct approach elsewhere.

---

## B. Observability

### B.1 — The two CLI flags: `--trace_to_cloud` vs `--otel_to_cloud`

Verified in `cli_tools_click.py` + `fast_api.py` + `api_server.py`:

| Flag | Status | What it does |
|---|---|---|
| `--trace_to_cloud` | **Deprecated** in 2.7.1 (`_deprecate_trace_to_cloud` callback fires a warning: `"...use --otel_to_cloud instead."`) — still present for backward compat, only active `if trace_to_cloud and not otel_to_cloud` | Old path: installs a bare `TracerProvider` with **only** a `BatchSpanProcessor(CloudTraceSpanExporter(project_id=...))` — **traces only, no logs, no metrics**. Requires `GOOGLE_CLOUD_PROJECT` env var set or it silently no-ops with a warning log (`"GOOGLE_CLOUD_PROJECT environment variable is not set. Tracing will not be enabled."`) |
| `--otel_to_cloud` | **Current/recommended** (still labeled experimental in some deploy help text) | Full path: `_setup_gcp_telemetry()` → `get_gcp_exporters(enable_cloud_tracing=True, enable_cloud_metrics=True, enable_cloud_logging=True, ...)` — **all three: Cloud Trace + Cloud Monitoring metrics + Cloud Logging**, wired via `maybe_set_otel_providers()`. Also installs request-metrics middleware (`maybe_install_request_metrics_middleware`) for HTTP-level request metrics on the FastAPI app. |

Both flags exist identically on: `adk run` family help block (`fast_api_common_options()`, ~line 1859/1866), `adk deploy cloud_run` (~line 2279/2289), `adk deploy agent_engine` (~line 2572/2581 — note: `--trace_to_cloud` here takes a `/--no-trace_to_cloud` boolean-flag form and is fully deprecated/no-op, `--otel_to_cloud` is the only live one for Agent Engine), `adk deploy gke` (~line 2840/2847).

**Practical directive for Foreman+: use `--otel_to_cloud` everywhere, never `--trace_to_cloud`.** It subsumes tracing and additionally gives Cloud Logging + Cloud Monitoring for free from one flag — directly maps to the hackathon's "Agent Observability" checklist item (traces AND logs AND metrics, not traces alone).

### B.2 — Precedence logic if you ALSO set raw OTel env vars

Verified, `api_server.py::_setup_telemetry()`:
```python
if otel_to_cloud:
    _setup_gcp_telemetry(...)                 # GCP exporters win
elif _otel_env_vars_enabled():                # any of OTEL_EXPORTER_OTLP_*_ENDPOINT set
    _setup_telemetry_from_env(...)             # generic OTLP exporter (any backend)
else:
    # bare TracerProvider, exporters only if `--trace_to_cloud` path added one
```
So **don't set both** `--otel_to_cloud` and a generic `OTEL_EXPORTER_OTLP_ENDPOINT` — the flag wins silently, your custom OTLP endpoint is ignored. If you want a third-party backend (Honeycomb/Datadog) instead of GCP, use the env-var path and omit `--otel_to_cloud`.

### B.3 — Env vars for `adk deploy cloud_run --otel_to_cloud`

- `GOOGLE_CLOUD_PROJECT` — required; without it the code path in `_setup_gcp_telemetry` calls `google.auth.default()` for `(credentials, project_id)` — on Cloud Run this resolves automatically from the metadata server, so **usually you don't need to set it manually when running ON Cloud Run**; you DO need it when testing `--otel_to_cloud` locally (`adk web --otel_to_cloud`) via `export GOOGLE_CLOUD_PROJECT=foreman-hackathon`.
- `GOOGLE_CLOUD_AGENT_ENGINE_ID` — only relevant on Agent Engine deploys, changes the resource-detection/log-exporter branch (`_get_agent_engine_logs_exporter` vs `_get_gcp_logs_exporter`); **not applicable to our Cloud Run deploy.**
- `GOOGLE_CLOUD_DEFAULT_LOG_NAME` — optional, default log name is `"adk-otel"` (`_DEFAULT_LOG_NAME` constant, `telemetry/google_cloud.py`).
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` — set to capture full prompt/response content in spans (default: **elided for security**, per live docs `adk.dev/observability/logging/`). Programmatic equivalent: `RunConfig.telemetry` with a `ContentCapturingMode` option (**UNVERIFIED exact enum values** — not traced in this pass, check `google/adk/agents/run_config.py`).

### B.4 — IAM roles needed on the Cloud Run runtime service account

**UNVERIFIED against live IAM docs this pass** (fetch returned generic guidance, not an authoritative role list) — standard-practice roles for the exporters actually used (`CloudTraceSpanExporter`, `CloudLoggingExporter`, GCP metric exporter):
- `roles/cloudtrace.agent` (write spans)
- `roles/logging.logWriter` (write log entries)
- `roles/monitoring.metricWriter` (write custom metrics)

Cloud Run's **default compute service account** typically already carries broad `Editor`-equivalent grants on new projects unless you've hardened it — if you're using a **custom minimal SA** for `foreman-agent@foreman-hackathon...` (per project CLAUDE.md, we already provisioned this SA for the Gemini key), grant these three explicitly before relying on `--otel_to_cloud` in production, and verify by checking Cloud Trace/Logging actually receive data (empty console = likely this, not a code bug — rule 27 ground-truth check, don't debug code first).

### B.5 — What spans/attributes you actually get (per-agent / per-tool)

Verified directly from `google/adk/telemetry/tracing.py` (module docstring: *"the information recorded by ADK should be focused on the higher-level constructs of the framework that are not observable by the [genai] SDK"*) — functions that create spans, with call sites:

| Span-producing function | Span name (`gen_ai.operation.name` attr) | Called from |
|---|---|---|
| `trace_agent_invocation()` | `invoke_agent` | agent run entry (per agent/sub-agent hop) |
| `trace_call_llm()` | `call_llm` | `flows/llm_flows/base_llm_flow.py:1475` — one span per LLM request/response |
| `trace_tool_call()` | (tool-specific) | individual tool invocation |
| `trace_merged_tool_calls()` | `execute_tool (merged)` | `flows/llm_flows/functions.py:516,764` — when the model calls multiple tools in one turn, they're merged into one span |
| `trace_send_data()` | `send_data` | `base_llm_flow.py:678` — streaming/bidi data send |
| — | `handle_context_caching` | `models/google_llm.py:213` — Gemini context-cache hit/miss |
| — | `create_cache` | `gemini_context_cache_manager.py:558` |
| — | `managed_agent_interaction` | `agents/_managed_agent.py:460` |

Key OTel GenAI semantic-convention attributes set on spans (imports in `tracing.py`, from `opentelemetry.semconv._incubating.attributes.gen_ai_attributes`): `gen_ai.agent.name`, `gen_ai.agent.description`, `gen_ai.conversation.id`, `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.response.finish_reasons`, `gen_ai.system`, `gen_ai.tool.call.id`, `gen_ai.tool.description`, `gen_ai.tool.name`, `gen_ai.tool.type`, plus `user.id` and `error.type`. Live-docs page additionally lists GCP-specific attrs added on top: `gcp.vertex.agent.invocation_id`, `gcp.vertex.agent.event_id`. This IS the "per-agent/per-tool span" answer for the hackathon checklist — every agent hop and every tool call is individually spanned and nameable in Trace Explorer's waterfall view, nested under the parent request span.

**A2A cross-service note (verified, `api_server.py:752` comment):** *"Set up HTTPX and gRPC instrumentation for A2A multi-agent observability"* — when `--a2a` is combined with `--otel_to_cloud`, ADK auto-instruments outbound `httpx`/`grpc` calls, so a trace started in service A (the caller) **propagates its trace context across the HTTP call into service B** (the remote A2A agent) automatically via standard W3C traceparent headers — you get ONE unified trace spanning both Cloud Run services in Trace Explorer, not two disconnected traces. This is a concrete, demoable "distributed multi-agent observability" story for judges if we do split into services (see A.5).

### B.6 — Custom OTel from Python (beyond the CLI flags)

Programmatic equivalent of `--otel_to_cloud`, for use inside our own code (e.g. a Cloud Function/worker that isn't served by `adk web`/`fast_api.py`, or to add custom spans around our own memory-write-gate logic):
```python
import google.auth
from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource
from google.adk.telemetry.setup import maybe_set_otel_providers

credentials, project_id = google.auth.default()
otel_hooks = get_gcp_exporters(
    enable_cloud_tracing=True,
    enable_cloud_metrics=True,
    enable_cloud_logging=True,
    google_auth=(credentials, project_id),
)
maybe_set_otel_providers(
    otel_hooks_to_setup=[otel_hooks],
    otel_resource=get_gcp_resource(project_id),
)
```
This is exactly what `_setup_gcp_telemetry()` does internally (`api_server.py`) — verified by direct source read, not inferred. For your OWN custom spans on top (e.g. wrapping our Postgres write-gate journal writes), use the standard `opentelemetry.trace` API after this setup:
```python
from opentelemetry import trace
tracer = trace.get_tracer("foreman.memory")
with tracer.start_as_current_span("write_gate.commit") as span:
    span.set_attribute("foreman.fact_count", n)
    ...
```
These custom spans land in the SAME Cloud Trace project/trace as ADK's own spans (shared global `TracerProvider`) — they'll nest correctly under `invoke_agent`/`call_llm` spans if created within the same async context, giving judges one coherent trace from "photo received" → "Gemini call" → "our DB write" → "response sent."

### B.7 — What to actually show judges (maps to "Agent Observability" checklist item)

1. **Cloud Trace → Trace Explorer**, filtered to the Cloud Run service: a waterfall for one repair-scoping request showing `invoke_agent` (Foreman) → `call_llm` (Gemini vision+text) → `execute_tool (merged)` (any tool calls) → nested child agent `invoke_agent` spans if delegated → response. Screenshot/recording of this waterfall is exactly the kind of console screenshot judges can be shown per the deliverable requirements (README/demo video asks for "Google Cloud... in action").
2. **Cloud Logging**, filtered `logName="adk-otel"` (or your custom `GOOGLE_CLOUD_DEFAULT_LOG_NAME`) — structured log entries correlated to trace IDs (click "Trace" link on a log entry to jump to Trace Explorer — this correlation is automatic because both exporters share the same `Resource`/trace-context).
3. **Cloud Monitoring**, custom metrics dashboard from `maybe_install_request_metrics_middleware` — request count/latency/error-rate per route, useful for a "production readiness" (30% judging weight) screenshot.
4. If we split services for A2A: a **single trace spanning both Cloud Run services**, proving distributed multi-agent tracing works — strongest visual for "Architectural Discipline" (30%) + "Innovation & Operational Utility" (40%, "autonomous execution" sub-criterion).

---

## C. Open items / follow-ups (not fully verified this pass)

- `A2aRemoteAgentConfig.request_interceptors` exact `before_request` return contract for attaching an ID-token header — read `google/adk/a2a/agent/config.py` in full + `.../a2a/agent/utils.py::execute_before_request_interceptors` before wiring auth.
- `RunConfig.telemetry` / `ContentCapturingMode` exact enum values for opting into full prompt/response capture — check `google/adk/agents/run_config.py`.
- Exact IAM role list for `--otel_to_cloud` — not found in an authoritative live IAM doc this pass; the three roles listed in B.4 are standard-practice inference, not doc-cited. Verify by testing empty-vs-populated Trace/Logging console after first deploy (ground truth beats doc-guessing per rule 27).
- Cloud Trace/Logging free-tier numbers: **could not get a clean live number this pass** (pricing page fetch returned truncated/no data; quotas page gave rate limits — 300 read-ops/min, 4,800 write-ops/min, 3M–5B spans/day ingestion ceiling depending on billing history — but not a "free $ amount"). Don't quote a specific free-tier $/span number to the team without re-checking `cloud.google.com/trace/pricing` directly in a browser.
- `to_a2a()` + `--a2a` CLI path both marked `@a2a_experimental` in this ADK version — re-check `google-adk` changelog before final submission in case 2.7.x → later patch changes the API surface (rule 38: check changelog on version bump, don't assume stability).

**Sources:** installed `google-adk==2.7.1` source tree (primary, cited by file:line above) · `https://adk.dev/a2a/quickstart-exposing/` · `https://adk.dev/a2a/quickstart-consuming/` · `https://adk.dev/integrations/cloud-trace/` (redirected from `/observability/cloud-trace/`) · `https://adk.dev/observability/logging/` · `https://docs.cloud.google.com/run/docs/authenticating/service-to-service` · `https://docs.cloud.google.com/trace/docs/quotas`.
