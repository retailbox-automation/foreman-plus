# ADK 2.7.1 — Sessions, State, Memory, Artifacts (cheatsheet)

Verified against **installed package** `google-adk==2.7.1` at
`.venv/lib/python3.14/site-packages/google/adk/` (file:line refs below) +
official docs (`google.github.io/adk-docs`, fetched live). Anything not
directly seen in source or a live-fetched official page is marked
**UNVERIFIED**. Also cross-checked against our own `docs/SPIKE-2026-08-19-adk-fleet.md`
(local Cloud Run + Cloud SQL end-to-end proof, 19.08.2026).

---

## 1. Session state — the 4 scopes

`sessions/state.py` — class `State(value, delta, schema=None)`, prefixes:

| Prefix | Constant | Scope | Persisted? |
|---|---|---|---|
| *(none)* | — | session-only | yes |
| `app:` | `State.APP_PREFIX` | shared across all users of the app | yes (own table) |
| `user:` | `State.USER_PREFIX` | shared across all sessions of one user | yes (own table) |
| `temp:` | `State.TEMP_PREFIX` | current invocation only | **no** — stripped before storage |

- `session.state[key] = value` sets both `_value` and `_delta` (state.py:88-95).
- **Optional Pydantic schema validation**: pass `schema=MyModel` to `State()`;
  keys containing `:` bypass validation entirely (state.py:32-33, 39-40) — so
  scoped keys are never schema-checked, only bare session keys are.
- `state.has_delta()` — whether there's an uncommitted delta.

### temp: mechanics (base_session_service.py:192-220)
`append_event()`:
1. `_apply_temp_state()` — writes `temp:` keys into the **in-memory**
   `session.state` first, so agents later in the *same invocation*
   (e.g. inside a `SequentialAgent`) can still read them via
   `output_key='temp:my_key'`.
2. `_trim_temp_delta_state()` — strips `temp:` keys from the `Event.actions.state_delta`
   **before** it's appended/persisted. Non-temp keys go through unmodified.
3. `_update_session_state()` — folds the (trimmed) delta into `session.state`.

So `temp:` state is real for the rest of the current turn but never touches
storage and vanishes on session reload.

### How app:/user: state maps to storage (`sessions/_session_util.py:41-57`)
`extract_state_delta(state)` splits any dict into `{"app": {...}, "user": {...}, "session": {...}}`
by stripping the prefix; `temp:` keys are dropped entirely here too. This is
what `DatabaseSessionService` uses to route writes to `app_states` /
`user_states` / `sessions.state` on `append_event`/`create_session`.

### Reading merged state
`session.state` you get back from `get_session()` is the **merge** of
session-scoped + `app:`-prefixed app state + `user:`-prefixed user state
(database_session_service.py:247-249 — `merged_state[State.APP_PREFIX+key]=...`).
You do not need to fetch app/user state separately in normal agent code.

`BaseSessionService.get_user_state(app_name, user_id)` (base_session_service.py:117-149)
reads `user:` state **without** an active session_id (useful to bootstrap
context before `create_session`). Returns raw (unprefixed) keys.
⚠️ **Not implemented by every service** — raises `NotImplementedError` unless
the concrete service supports it; fall back to `list_sessions` + `get_session`.

---

## 2. Session services — comparison

| Service | Class (module) | Persists? | Survives process restart? | Use case |
|---|---|---|---|---|
| **InMemory** | `InMemorySessionService` (`sessions/in_memory_session_service.py`) | No | No | local dev/tests, ADK CLI default *if* agent dir isn't writable or on Cloud Run/K8s |
| **SQLite (legacy)** | `SqliteSessionService` (`sessions/sqlite_session_service.py`) | Yes, local file | Yes | the ADK CLI/`adk web` **default local storage** (per-agent `.adk/` dir) — see §5 |
| **Database (SQLAlchemy)** | `DatabaseSessionService` (`sessions/database_session_service.py`) | Yes, any SQLAlchemy-async DB | Yes | **production** — Postgres/MySQL/Spanner/AlloyDB via async driver |
| **VertexAiSessionService** | `sessions/vertex_ai_session_service.py` | Yes, managed by Vertex AI Agent Engine | Yes | fully managed, GCP-native, supports `ttl`/`expire_time` per session |

### DatabaseSessionService — constructor (database_session_service.py:273-336)
```python
from google.adk.sessions import DatabaseSessionService

# Option A — URL (creates its own AsyncEngine)
svc = DatabaseSessionService(
    db_url="postgresql+asyncpg://user:pass@host:5432/dbname",
    # **kwargs passed straight to sqlalchemy.create_async_engine
)

# Option B — bring your own AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine("postgresql+asyncpg://...")
svc = DatabaseSessionService(db_engine=engine)
```
- Exactly one of `db_url` / `db_engine` — passing both or neither raises `ValueError`.
- Requires the **`db` extra**: `pip install 'google-adk[db]'` (pulls in
  `sqlalchemy>=2,<3` + `sqlalchemy-spanner`). **`asyncpg` is NOT pulled in by
  `[db]`** (verified: `Requires-Dist` for extra "db" lists only sqlalchemy +
  sqlalchemy-spanner) — install it yourself: `pip install asyncpg greenlet`.
  Our `foreman_app/requirements.txt`: `google-adk[db]==2.7.1`, `asyncpg`, `greenlet`.
- **The URL MUST name an async driver** — `postgresql+asyncpg://`, not bare
  `postgresql://` (SQLAlchemy's `create_async_engine` errors if the resolved
  DBAPI isn't async-capable). Bare `postgresql`/`mysql` schemes ARE recognized
  by the CLI's URI registry (service_registry.py:290-293) and routed to
  `DatabaseSessionService(db_url=uri)` too, but you still need the driver
  suffix in the actual string for it to connect.
- Non-SQLite dialects get `pool_pre_ping=True` set automatically (database_session_service.py:347-348).
- SQLite `:memory:` URLs get `StaticPool` + `check_same_thread=False` auto-set.
- **Tables are created lazily** on first real use (`self._tables_created` flag
  + `asyncio.Lock()` guard, database_session_service.py:382-386) — no manual
  migration step for a fresh database.
- Per-session **in-process locks** serialize `append_event` calls for the same
  `(app_name, user_id, session_id)` (database_session_service.py:389-391) —
  concurrency safety within one process only, not across replicas.

### Schema versions (v0 / v1) — auto-detected, not chosen by you
`sessions/migration/_schema_check_utils.py:37-89`:
- **v0** (`SCHEMA_VERSION_0_PICKLE`, value `"0"`) — legacy: `events` table with
  an `actions` column, event data was **Python-pickled**. Detected when
  `events` table exists, has `actions` col, lacks `event_data` col, and there's
  no `adk_internal_metadata` table. **Deprecated**, logs a warning telling you
  to run `adk migrate session`.
- **v1** (`SCHEMA_VERSION_1_JSON`, value `"1"`, = `LATEST_SCHEMA_VERSION`) —
  current: `events.event_data` is a JSON blob (`schemas/v1.py`), plus an
  `adk_internal_metadata` key/value table recording `schema_version`.
- **A brand-new database gets v1 directly.** Version is read from
  `adk_internal_metadata` if that table exists; otherwise inferred from the
  `events` table shape; otherwise assumed latest.
- v1 tables (schemas/v1.py): `sessions` (PK `app_name,user_id,id`; `state` JSON;
  `create_time`/`update_time`), `events` (PK `id,app_name,user_id,session_id`;
  FK → sessions ON DELETE CASCADE; `event_data` JSON; indexed on
  `(app_name,user_id,session_id,timestamp DESC)`), `app_states` (PK `app_name`),
  `user_states` (PK `app_name,user_id`), `adk_internal_metadata` (PK `key`).
- **Optimistic concurrency**: `StorageSession.get_update_marker()` returns an
  ISO timestamp used as a stale-write check — `append_event` raises
  `StaleSessionError` if the in-memory `Session` you're appending to was
  loaded before another writer already updated the row (database_session_service.py,
  `_STALE_SESSION_ERROR_MESSAGE`). Reload the session and retry on that error.

### VertexAiSessionService (sessions/vertex_ai_session_service.py)
- Managed by Vertex AI **Agent Engine** — session IDs may come back as full
  resource names (`.../sessions/<id>`); `_extract_short_session_id()` strips
  the prefix, matching an optional `expected_engine_id`.
- Supports **`ttl`** (e.g. `ttl='7200s'`) or **`expire_time`**
  (ISO8601, e.g. `'2025-10-01T00:00:00Z'`) kwargs on session create — mutually
  exclusive, `ValueError` if both given (vertex_ai_session_service.py:179-189).
  This is ADK's only **built-in session TTL** mechanism — `DatabaseSessionService`
  has none (see §4).
- URI scheme for CLI/deploy: `agentengine://<reasoning_engine_id_or_resource_name>`
  (service_registry.py `agentengine_session_factory`, uses
  `_parse_agent_engine_kwargs`). **UNVERIFIED**: exact accepted formats of the
  netloc+path beyond "parsed as agent-engine kwargs" — didn't trace
  `_parse_agent_engine_kwargs` fully.

### InMemorySessionService — merge logic (sessions/in_memory_session_service.py:225-243)
Same app:/user: merge pattern as DatabaseSessionService but backed by plain
dicts (`self.app_state[app_name]`, `self.user_state[app_name][user_id]`).
Zero persistence — restart = empty. This is what a bare `Runner()` uses if you
don't pass a `session_service`.

---

## 3. Events — what gets persisted

- `Event` objects (from `events/event.py`) are appended via
  `BaseSessionService.append_event(session, event)`. Partial events
  (`event.partial == True`, i.e. streaming deltas) are **not** appended at all
  — returned as-is (base_session_service.py:186-187).
- On `DatabaseSessionService`, each accepted event becomes one `StorageEvent`
  row: `event_data = event.model_dump(exclude_none=True, mode="json")`
  (schemas/v1.py `from_event`) — the **entire Event** (content, actions,
  usage_metadata, etc.) as JSON, keyed by the event's own `id`.
- On read-back (`to_event()`), the **stored `timestamp` inside `event_data`
  wins** over the SQL `timestamp` column — the column is a naive local
  datetime and reconstructing an epoch from it can land on the wrong instant
  across a DST fall-back; the code explicitly prefers the JSON payload's
  epoch (schemas/v1.py comment + code, `to_event`).
- `event.actions.state_delta` is what actually mutates state on append
  (`_update_session_state`, base_session_service.py:222-227) — an event with
  no `actions.state_delta` doesn't touch state at all.

---

## 4. `GetSessionConfig` — reading a slice of a session

```python
from google.adk.sessions import GetSessionConfig

session = await session_service.get_session(
    app_name=..., user_id=..., session_id=...,
    config=GetSessionConfig(num_recent_events=20, after_timestamp=1234567890.0),
)
```
(base_session_service.py:29-42)
- `num_recent_events`: `None` = no limit; `0` = **zero events returned** (state
  is still returned); `>0` = last N events.
- `after_timestamp`: only events with `timestamp >= value`.
- Both filters can combine.

### TTL / cleanup — no built-in janitor for Database/Sqlite/InMemory
- `DatabaseSessionService` / `SqliteSessionService` / `InMemorySessionService`
  have **no TTL, no auto-expiry, no background cleanup**. The only removal
  path is your own explicit `await session_service.delete_session(app_name=...,
  user_id=..., session_id=...)` (cascades to that session's events via the FK
  `ondelete="CASCADE"` for the DB service). **Pattern for a hackathon/production
  app: run your own cron/cleanup job (e.g. Cloud Scheduler → Cloud Run job)
  that lists old sessions and calls `delete_session`.** UNVERIFIED beyond the
  source-level absence of any expiry code — no official doc page found stating
  a recommended cadence.
- Only `VertexAiSessionService` (`ttl`/`expire_time`) and
  `VertexAiMemoryBankService` (`ttl`/`revision_ttl` in `custom_metadata`,
  `memory/vertex_ai_memory_bank_service.py:54-72`) have managed expiry.

---

## 5. Memory services — distinct from Session services

Memory ≠ session state: memory is a **separate, searchable store** you
explicitly feed from sessions, used to answer "what did we discuss before"
across *different* sessions for the same user.

| Service | Search | Notes |
|---|---|---|
| `InMemoryMemoryService` (`memory/in_memory_memory_service.py`) | keyword/word-overlap only (`re.findall(r'\w+', ...)`, `_extract_words_lower`) | **"for prototyping purpose only"** per its own docstring; thread-safe but not for prod (in_memory_memory_service.py:44-51) |
| `VertexAiRagMemoryService` (`memory/vertex_ai_rag_memory_service.py`) | Vertex AI RAG corpus (semantic) | URI: `rag://<rag_corpus_id>`, resolves to `projects/{project}/locations/{location}/ragCorpora/{corpus}` (service_registry.py `rag_memory_factory`) |
| `VertexAiMemoryBankService` (`memory/vertex_ai_memory_bank_service.py`) | Vertex AI Memory Bank (managed, semantic, supports TTL) | URI: `agentengine://<engine_id>` |

### BaseMemoryService contract (`memory/base_memory_service.py`)
- `add_session_to_memory(session)` — abstract, ingest a whole session (can be
  called multiple times over a session's life).
- `add_events_to_memory(app_name, user_id, events, session_id=None,
  custom_metadata=None)` — optional; NotImplementedError by default. For
  incremental (delta) ingestion instead of re-ingesting the full session.
- `add_memory(app_name, user_id, memories: Sequence[MemoryEntry],
  custom_metadata=None)` — optional; direct writes without going through a
  session at all. NotImplementedError unless the concrete service supports it.
- `search_memory(app_name, user_id, query) -> SearchMemoryResponse` — abstract,
  every implementation must support this.
- `MemoryEntry` (`memory/memory_entry.py`): `content: types.Content`,
  `custom_metadata: dict`, `id`, `author`, `timestamp` (ISO 8601 string,
  forwarded to the LLM).

### `load_memory` tool vs `preload_memory` tool (both call `tool_context.search_memory(query)`)
| | `load_memory` | `preload_memory` |
|---|---|---|
| Type | `FunctionTool` — model **decides** to call it | `BaseTool` — runs **automatically** every `llm_request`, model never calls it |
| Query | model-supplied `query: str` arg | the current turn's `user_content` text, used verbatim |
| Injection | returns `LoadMemoryResponse` as a tool result | injects a `<PAST_CONVERSATIONS>` block as a transient user-content message via `llm_request._insert_transient_user_content()` |
| Failure | propagates | swallowed — `except Exception: logging.warning(...); return` (silently no-ops on memory-service errors) |
| Import | `from google.adk.tools import load_memory` | `from google.adk.tools import preload_memory` |

Neither tool is memory-service-specific — both just call whatever
`BaseMemoryService` is wired into the `Runner`/`InvocationContext`.

---

## 6. Artifact services

| Service | Module | Backend | Notes |
|---|---|---|---|
| `InMemoryArtifactService` | `artifacts/in_memory_artifact_service.py` | dict | dev only |
| `FileArtifactService` | `artifacts/file_artifact_service.py` | local filesystem | URI `file:///abs/path` |
| `GcsArtifactService` | `artifacts/gcs_artifact_service.py` | GCS bucket | URI `gs://<bucket-name>` |

### GcsArtifactService blob naming (gcs_artifact_service.py:16-21, module docstring)
```
user-namespaced (filename starts "user:"):  {app_name}/{user_id}/user/{filename}/{version}
session-scoped:                             {app_name}/{user_id}/{session_id}/{filename}/{version}
```
Versions are plain integers appended to the blob name; `_parse_version()`
lists by prefix and only accepts blobs whose name is exactly
`{prefix}{version}` (guards against GCS's flat namespace matching nested
artifacts whose names happen to contain `/`).
Constructor: `GcsArtifactService(bucket_name=...)` — extra kwargs from the
`gs://` URI (minus `agents_dir`/`per_agent`) are forwarded.

### `--artifact_service_uri` accepted schemes (service_registry.py:296-330)
`memory` (dict), `gs` (GCS bucket), `file` (local `file://` path — netloc
must be empty or `localhost`, path required). No Vertex-managed artifact
service is registered in this version — **UNVERIFIED** whether one exists
under a different mechanism.

---

## 7. `adk deploy cloud_run` — service URI flags & Cloud Run behavior

CLI flags (from `cli/cli_deploy.py` / `cli/cli_tools_click.py`, confirmed by
grep — exact `click` option strings not individually re-verified char-for-char,
flag **names** are correct): `--session_service_uri`, `--artifact_service_uri`,
`--memory_service_uri`.

### 🔴 Cloud Run/K8s auto-fallback to in-memory (`cli/utils/service_factory.py:120-136`)
This is the single most important gotcha for a hackathon deploy:
```python
if _is_cloud_run() or _is_kubernetes():
    # "Detected Cloud Run/Kubernetes runtime; using in-memory services
    #  instead of local .adk storage. Set ADK_FORCE_LOCAL_STORAGE=1 to force."
    return False, warning_message   # → in-memory, NOT local sqlite
```
`_is_cloud_run()` checks env var `K_SERVICE` (set automatically by Cloud Run);
`_is_kubernetes()` checks `KUBERNETES_SERVICE_HOST`. **If you deploy to Cloud
Run WITHOUT passing `--session_service_uri` explicitly, ADK silently falls
back to `InMemorySessionService`** even though local-file storage would
otherwise be the default — because the container filesystem is ephemeral and
per-instance. Every new revision (or even a second concurrently-scaled
instance) starts with a blank memory. Confirmed independently in our own
19.08 Cloud Run spike: *"Каждый `gcloud run services update` = новая ревизия
= in-memory сессии стёрты"*.
**⇒ Always pass `--session_service_uri postgresql+asyncpg://...` (or
`agentengine://...`) explicitly when deploying to Cloud Run if you need
sessions to survive a redeploy or to be shared across instances.**

Same fallback logic applies to `create_artifact_service_from_options` — no
`--artifact_service_uri` on Cloud Run ⇒ `InMemoryArtifactService`, not local
disk.

Env var escape hatches (service_factory.py):
- `ADK_DISABLE_LOCAL_STORAGE=1` — force in-memory everywhere (with a log warning).
- `ADK_FORCE_LOCAL_STORAGE=1` — force local `.adk/` storage even on Cloud
  Run/K8s (only if the directory is actually writable — Cloud Run's default fs
  IS writable but ephemeral, so this doesn't survive a redeploy either, it
  just avoids the auto-downgrade to pure in-memory for a single running
  instance).

### Default local behavior (non-Cloud-Run, e.g. `adk web` / `adk run` locally)
No `--session_service_uri` given, agents dir is writable, not on Cloud
Run/K8s ⇒ `create_local_session_service(base_dir, per_agent=True)` — SQLite
per-agent under `<agents_root>/<agent>/.adk/` (service_factory.py:195-201).
This is **not** `DatabaseSessionService` — it's the lighter-weight
`SqliteSessionService` local-storage path (`DotAdkFolder`).

### Custom URI schemes without code — `services.yaml` / `services.py`
Drop a `services.yaml` (or `.py`) in the agent directory to register
additional session/artifact/memory factories for custom URI schemes
(`cli/service_registry.py` module docstring, lines 14-56) — YAML loaded
first, then `services.py` (which can override a YAML-defined scheme).

---

## 8. Known-good end-to-end pattern (matches our project + verified live)

```
Cloud Run (foreman-hello) ──┐
                             ├─ --session_service_uri postgresql+asyncpg://…@/db?host=/cloudsql/PROJECT:REGION:INSTANCE
                             └─ --add-cloudsql-instances PROJECT:REGION:INSTANCE
                                      │
                                      ▼
                          Cloud SQL Postgres 16 (unix socket)
                          tables: sessions / events / app_states /
                                  user_states / adk_internal_metadata
```
`requirements.txt` alongside the agent (picked up automatically by
`adk deploy cloud_run`'s generated Dockerfile — the **default** Dockerfile
does NOT include SQLAlchemy/asyncpg, so a bare deploy with `--session_service_uri`
set crashes the container on `ModuleNotFoundError: sqlalchemy` and the OLD
revision keeps serving traffic silently — verified in our 19.08 spike, gotcha #5):
```
google-adk[db]==2.7.1
asyncpg
greenlet
```
`GOOGLE_GENAI_USE_VERTEXAI=FALSE` + `GOOGLE_CLOUD_LOCATION=global` needed when
using a bound-service-account API key (format `AQ.…`) — otherwise the SDK
auto-routes through the Vertex AI surface (403 aiplatform disabled → then 404
"model not found in <cloud-run-region>"). Full narrative:
`docs/SPIKE-2026-08-19-adk-fleet.md`.

---

## Sources
- Installed package: `.venv/lib/python3.14/site-packages/google/adk/` (ADK
  **2.7.1**, `google_adk-2.7.1.dist-info/METADATA` for extras) — all file:line
  references above point here.
- Official docs (WebFetch not needed beyond package `METADATA`/source — the
  installed source was authoritative and matched our own prior live Cloud Run
  test; no contradictions found against `google.github.io/adk-docs` general
  knowledge of session/state concepts, but exact current doc-site wording was
  **not independently re-fetched** for this pass — treat source-derived facts
  above as primary, doc-site as UNVERIFIED where not explicitly cited).
- Our own verified spike: `docs/SPIKE-2026-08-19-adk-fleet.md` (19.08.2026,
  local + Cloud Run + Cloud SQL, independently `psql`-checked).

## UNVERIFIED (flagged explicitly, do not treat as fact)
- Exact `agentengine://` URI grammar beyond "netloc+path parsed as agent-engine kwargs".
- Whether a managed (non-GCS) artifact service exists in any ADK extra not installed here.
- Exact `click` option help text for `--session_service_uri` et al. (names confirmed via grep, full `--help` output not captured).
- Recommended session-cleanup cadence/pattern — no official doc page located; the "no built-in TTL for DB/Sqlite/InMemory" fact IS verified from source, only the "recommended cron cadence" advice is our own inference.
