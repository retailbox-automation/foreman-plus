# ADK 2.7 Core Cheatsheet (Foreman+)

Installed: **`google-adk==2.7.1`** (verified: `.venv/lib/python3.14/site-packages/google_adk-*.dist-info/METADATA`, `version.py`).
Source of truth for everything below = the installed package under
`.venv/lib/python3.14/site-packages/google/adk/`, cross-checked against live docs where noted.
Official docs root: https://google.github.io/adk-docs/ (Python) — WebFetch on that domain **timed out
twice during this pass**; sections below marked `[pkg-verified]` come straight from installed source
(highest-confidence ground truth per rule 27), `[UNVERIFIED-vs-live-docs]` means only source was checked,
not cross-read against the hosted docs page.

---

## 1. Agent / LlmAgent — constructor params `[pkg-verified: agents/llm_agent.py, agents/base_agent.py]`

`Agent` is an alias: `from google.adk.agents import Agent` → same class as `LlmAgent`
(`Agent = LlmAgent` in `agents/__init__.py`).

```python
from google.adk.agents import Agent  # == LlmAgent
```

### Fields that matter for us (all on `LlmAgent`, Pydantic model, `abc.ABC` — must subclass or use `Agent`)

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | required (on `BaseAgent`), must be unique among siblings |
| `model` | `Union[str, BaseLlm]` | `''` = inherit from parent agent, else `LlmAgent.DEFAULT_MODEL` = **`gemini-3.5-flash`** (built-in class default, `ClassVar`) |
| `instruction` | `Union[str, InstructionProvider]` | dynamic instr., supports `{state_var}` placeholders resolved at runtime from session state. Goes to `system_instruction` **unless** `static_instruction` is set, in which case it goes into user content (for cache-prefix ordering) |
| `global_instruction` | `Union[str, InstructionProvider]` | **DEPRECATED** — "will be removed in a future version. Use GlobalInstructionPlugin instead." Only the root agent's `global_instruction` takes effect anyway. Prefer `GlobalInstructionPlugin` (App-level) for shared identity/personality. |
| `static_instruction` | `Optional[types.ContentUnion]` | literal, no template substitution, no placeholders — sent first as system instruction, for context-cache prefix optimization. Accepts `str`, `types.Content`, `types.Part`, `PIL.Image.Image`, `types.File`, `list[PartUnion]`. Setting it alone does **not** enable caching — you still need `context_cache_config` on the `App` (§5). |
| `sub_agents` | `list[BaseAgent]` | on `BaseAgent`, not `LlmAgent`. Names must be unique (`field_validator('sub_agents', mode='after')`). Each sub-agent's `parent_agent` gets auto-set — **raises if a sub-agent already has a different parent** (can't share one agent instance across two parents; clone it instead, `BaseAgent.clone()`) |
| `tools` | `list[ToolUnion]` | `ToolUnion = Union[Callable, BaseTool, BaseToolset]` — plain functions get auto-wrapped |
| `output_key` | `Optional[str]` | writes the agent's final text reply into `session.state[output_key]` after each turn (`__maybe_save_output_to_state`) — the standard way to hand data to sibling/parent agents or callbacks |
| `generate_content_config` | `Optional[types.GenerateContentConfig]` | temperature/safety/etc. **Must NOT set** `.tools`, `.system_instruction`, `.response_schema`, or `.http_options.base_url` on it — validator raises if you do (those are owned by `tools=`, `instruction=`, `output_schema=`, and the model client respectively) |
| `mode` | `Literal['chat','task','single_turn'] \| None` | delegation mode. Default: `chat` when used as sub-agent, `single_turn` when used as a workflow node. `task`-mode root agents run to completion via a `finish_task` tool. |
| `disallow_transfer_to_parent` / `disallow_transfer_to_peers` | `bool` | gate `transfer_to_agent` targets (§2) |
| `include_contents` | `Literal['default','none']` | `'none'` = agent gets **no prior conversation history**, only its instruction + current turn |
| `input_schema` / `output_schema` | `Optional[type[BaseModel]]` / `SchemaType` | `output_schema` can be `type[BaseModel]`, `list[BaseModel]`, `list[primitive]`, raw `dict`, or `types.Schema`. **`output_schema` + `tools` together are supported**: ADK exposes tools during the reasoning loop and only enforces structure on the *final* output. |
| `planner` | `Optional[BasePlanner]` | e.g. `BuiltInPlanner` for native thinking |
| `code_executor` | `Optional[BaseCodeExecutor]` | e.g. `BuiltInCodeExecutor` |
| `before_model_callback`, `after_model_callback`, `on_model_error_callback`, `before_tool_callback`, `after_tool_callback`, `on_tool_error_callback` | see §4 | each accepts **a single callback or a `list[...]`** — for `before_*`, the chain stops at the first non-`None` return |

### Minimal working agent
```python
from google.adk.agents import Agent

triage = Agent(
    name="triage",
    model="gemini-3.6-flash",
    instruction="You triage repair requests. Extract device, issue, urgency.",
    sub_agents=[scoping_agent, dispatch_agent],
    tools=[lookup_manual],
    output_key="triage_result",
)
```

---

## 2. `transfer_to_agent` mechanics `[pkg-verified: flows/llm_flows/agent_transfer.py, tools/transfer_to_agent_tool.py]`

- It is **not something you add to `tools=`** — ADK auto-injects a `TransferToAgentTool` and an
  instruction block into every `LlmAgent` request via the `_AgentTransferLlmRequestProcessor`
  (`flows/llm_flows/agent_transfer.py`), on **every LLM call**, whenever the current agent has any
  transfer targets.
- **Transfer targets = `sub_agents` (excluding `mode in ('single_turn','task')`) + parent (unless
  `disallow_transfer_to_parent`) + peer sub-agents of the parent (unless `disallow_transfer_to_peers`)**.
  So a mid-tree agent can transfer to its own children, its parent, AND its siblings by default.
- Injected instruction text (verbatim structure, `_build_transfer_instruction_body`):
  > "You have a list of other agents to transfer to: … If you are the best to answer the question
  > according to your description, you can answer it. If another agent is better … call
  > `transfer_to_agent` function to transfer the question to that agent. When transferring, do not
  > generate any text other than the function call."
  — **`agent.description` is what the LLM sees to decide** — a blank/vague description on a sub-agent
  means the parent's transfer decisions will be bad. Always set `description=`.
- Actual mechanism: the tool function is
  ```python
  def transfer_to_agent(agent_name: str, tool_context: ToolContext) -> None:
      tool_context.actions.transfer_to_agent = agent_name
  ```
  The flow loop (`flows/llm_flows/base_llm_flow.py`) reads `event.actions.transfer_to_agent` after each
  event and switches execution to that agent — it's an `EventActions` side-channel, not a return value.
- `mode='task'` or `mode='single_turn'` agents get **no transfer instructions at all** (`_build_transfer_instructions` returns `''`) — they're leaf/worker nodes, not chat participants.

### The "uncached prefix on transfer" warning — where it comes from and how to silence it
`[pkg-verified: runners.py `_warn_uncached_agent_transfer`, lines ~483-499]`

```python
def _warn_uncached_agent_transfer(self) -> None:
    if self.context_cache_config is not None:
        return
    ...
    logger.warning(
        'App "%s" can transfer between agents but has no'
        ' context_cache_config. Every transfer swaps the system instruction'
        ' and the tool set, so the request prefix changes and the whole'
        ' prompt is re-sent uncached after each transfer. Set'
        ' context_cache_config on the app to give each agent its own cache.',
        ...)
```
This fires **once per `app_name`**, at `Runner.__init__`, if `self.agent` has any inter-agent transfer
capability (`_can_transfer_between_agents`) and `App.context_cache_config is None`. **Fix: set
`context_cache_config` on the `App`** (not on `Runner.__init__` directly — pass it via `app=App(...)`,
see §5). The warning is purely diagnostic; caching is opt-in and off by default.

---

## 3. `Runner` + `run_async` events API `[pkg-verified: runners.py]`

```python
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService  # see below

runner = Runner(
    app_name="foreman",          # required when passing `agent=`
    agent=root_agent,            # exactly one of app / agent / node
    session_service=DatabaseSessionService(db_url=DB_URL),
    artifact_service=None,       # optional
    memory_service=None,         # optional
    auto_create_session=False,   # default False: missing session -> ValueError, not silent create
)
```
- **Exactly one of `app`, `agent`, `node` must be given.** Passing `agent=` requires `app_name=`
  (raises `ValueError` otherwise). Passing `app=App(...)` is the *recommended* path — lets you set
  `context_cache_config`, `resumability_config`, `plugins` in one place. `Runner()` internally wraps
  bare `agent=`/`node=` into an `App.model_construct(...)`.
- `Runner.agent` after init is **not always an `LlmAgent`** — it's typed `BaseNode` (workflow graphs are
  a valid root too).

### `run_async` signature
```python
async def run_async(
    self, *,
    user_id: str,
    session_id: str,
    invocation_id: Optional[str] = None,   # set to RESUME an interrupted invocation
    new_message: Optional[types.Content] = None,
    state_delta: Optional[dict[str, Any]] = None,
    run_config: Optional[RunConfig] = None,
    yield_user_message: bool = False,      # True = also yield the user's own message as an Event
) -> AsyncGenerator[Event, None]
```
- Raises `ValueError` if the session doesn't exist (unless `auto_create_session=True` at Runner init)
  and if both `invocation_id` and `new_message` are `None`.
- `new_message.role` is auto-set to `'user'` if unset.
- Root `LlmAgent.mode` defaults to `'chat'` on first `run_async` call if unset. `mode='task'` root
  agents are driven to completion internally via a `finish_task` tool; only `'chat'`/`'task'` are legal
  for a root `LlmAgent` — anything else raises `ValueError`.
- There is also a **sync** `run()` (a `Generator[Event, None, None]`) — it spins `run_async` in a
  background thread. Docstring: *"This sync interface is only for local testing... use `run_async` for
  production."*

### Consuming events (`google.adk.events.event.Event`, `LlmResponse` subclass)
Key fields you'll actually touch: `event.author` (which agent emitted it), `event.content`
(`types.Content`, inherited from `LlmResponse`), `event.actions` (`EventActions` — `transfer_to_agent`,
`state_delta`, `skip_summarization`, etc.), `event.is_final_response()` (bool method — true once per
participating agent per turn), `event.long_running_tool_ids`, `event.branch`, `event.id`,
`event.invocation_id`, `event.timestamp`.

```python
async for event in runner.run_async(user_id=uid, session_id=sid, new_message=msg):
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.text:
                print(f"[{event.author}] {part.text}")
    if event.is_final_response():
        ...
```

---

## 4. `FunctionTool` from plain functions `[pkg-verified: tools/function_tool.py, tools/_automatic_function_calling_util.py, utils/context_utils.py]`

You almost never construct `FunctionTool` explicitly — pass a bare `async def`/`def` in `tools=[...]`
and `LlmAgent._convert_tool_union_to_tools` wraps it. Explicit form:
```python
from google.adk.tools import FunctionTool
FunctionTool(my_func, require_confirmation=False)  # require_confirmation: bool | Callable[..., bool]
```

### Schema generation
`build_function_declaration` (`tools/_automatic_function_calling_util.py`) inspects the function
signature + type hints via `pydantic.create_model` and maps Python types to `google.genai.types.Type`:

| Python annotation | Gemini schema type |
|---|---|
| `str` | `STRING` |
| `int` | `INTEGER` |
| `float` | `NUMBER` |
| `bool` | `BOOLEAN` |
| `list` / `List[...]` | `ARRAY` |
| `tuple` | `ARRAY` |
| `dict` / `Dict[...]` | `OBJECT` |
| unannotated / `Any` | `TYPE_UNSPECIFIED` |
| Pydantic `BaseModel` | nested `OBJECT` schema |
| `Optional[T]` | pydantic-schema `anyOf [T, null]`, made optional |

The declaration build is **`functools.lru_cache`d (maxsize=1024)** keyed on `(func, ignore_params,
variant, json_schema_enabled)` — so mutating a closed-over default *after* the tool is built won't
change the schema; redefine the function if you need a different schema.

- **Docstring becomes the tool description** — write a clear one-liner + `Args:`/`Returns:` (Google
  style); the model reads this to decide when to call the tool.
- **Return value**: whatever you return is coerced into the tool response dict; returning a `dict`
  directly is passed through, non-dict values get wrapped (check `base_tool.py` if you need the exact
  wrapping — not verified in this pass).

### `ToolContext` injection — automatic, by type annotation
```python
def my_tool(photo_url: str, tool_context: ToolContext) -> dict:
    tool_context.state["last_scope"] = ...
    return {"status": "ok"}
```
`find_context_parameter` (`utils/context_utils.py`) scans the function signature via
`inspect.signature` + `typing.get_type_hints`, finds the **first parameter annotated `Context` or a
type alias of it** (`ToolContext`, `CallbackContext` — both are aliases for `agents.context.Context` as
of 2.7.1, see below), and that parameter is **excluded from the generated JSON schema** and injected by
ADK at call time. Parameter name doesn't matter, only the type annotation does. You do **not** add it to
`ignore_params` yourself.

⚠️ **`ToolContext` is now literally `= Context`** (`tools/tool_context.py`: `ToolContext = Context`), not
its own class — a 2.7-era change from earlier ADK docs that describe a distinct `ToolContext` type.
Useful members on it (`agents/context.py`): `.state` (session `State`, dict-like, read/write), `.actions`
(`EventActions` — set `.transfer_to_agent`, `.skip_summarization`, `.state_delta`, etc.), `.session`
(read-only `Session`), `.function_call_id`, `.load_artifact(...)` (async).

### Supported param types (what you can safely annotate)
`str`, `int`, `float`, `bool`, `list[T]`, `dict`, `tuple`, Pydantic `BaseModel` subclasses,
`Optional[T]`/`T | None`, `Union[...]`. Unsupported / unusual annotations raise via
`_function_parameter_parse_util._raise_for_unsupported_param` at declaration-build time — build the
tool once at import time (or first call) to catch schema errors early rather than at agent-run time.

---

## 5. Callbacks `[pkg-verified: agents/llm_agent.py lines 76-134]`

All six callback fields on `LlmAgent` accept **either a single callable or `list[callable]`**. For
`before_*` callbacks, ADK calls them in list order and **stops at the first one that returns non-`None`**
(that return value short-circuits the actual model/tool call). `after_*` callbacks the same way, over the
already-produced response.

| Callback | Signature | Return semantics |
|---|---|---|
| `before_model_callback` | `(CallbackContext, LlmRequest) -> LlmResponse \| None` (sync or async) | non-`None` → skip the LLM call, return this response instead |
| `after_model_callback` | `(CallbackContext, LlmResponse) -> LlmResponse \| None` | non-`None` → replaces the actual model response |
| `on_model_error_callback` | `(CallbackContext, LlmRequest, Exception) -> LlmResponse \| None` | non-`None` → swallows the error, returns this |
| `before_tool_callback` | `(BaseTool, dict[str, Any], ToolContext) -> dict \| None` | non-`None` → skip calling the real tool, use this as the tool result |
| `after_tool_callback` | `(BaseTool, dict[str, Any], ToolContext, dict) -> dict \| None` | non-`None` → replaces the tool result |
| `on_tool_error_callback` | `(BaseTool, dict[str, Any], ToolContext, Exception) -> dict \| None` | non-`None` → swallows the error |

```python
def guard_pii(callback_context, llm_request):
    if "ssn" in str(llm_request):
        return LlmResponse(...)  # blocks the call
    return None  # proceed normally

agent = Agent(..., before_model_callback=guard_pii)
```
`CallbackContext` (used by model callbacks) is a superset of `Context`/`ToolContext` for our purposes —
same `.state`/`.actions` access pattern.

---

## 6. `context_cache_config` — App-level, not per-agent `[pkg-verified: agents/context_cache_config.py, apps/app.py]`

```python
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App

app = App(
    name="foreman",
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(
        cache_intervals=10,   # default 10, range 1-100: max invocations to reuse one cache before refresh
        ttl_seconds=1800,     # default 1800 (30 min)
        min_tokens=0,         # default 0: min PRIOR-request prompt tokens before caching kicks in
        create_http_options=None,  # types.HttpOptions, e.g. timeout on CachedContent.create()
    ),
)
runner = Runner(app=app, session_service=..., ...)
```
- **`@experimental(FeatureName.AGENT_CONFIG)`** decorated — API may change in a future ADK release.
- **Set it on `App`, then pass `app=` to `Runner`**, not directly on `Runner(...)` — `Runner` just reads
  `app.context_cache_config` (`self.context_cache_config = app.context_cache_config` in `__init__`).
  There is no `Runner(context_cache_config=...)` kwarg.
- **When it's `None` (default), caching is fully disabled** for the app, and that's exactly what
  triggers the "uncached prefix on transfers" warning from §2 whenever the agent tree can transfer.
- **Gating rule (docstring, verbatim):** "Caching begins on the second turn of a session at the
  earliest and requires the cacheable prefix to reach the model-specific minimum: 2048 tokens for
  Gemini 2.5 or 4096 tokens for Gemini 3. Short or single-turn sessions are therefore never cached."
  `min_tokens` gates on the **previous request's actual prompt token count**, not an estimate of the
  current one — so it does nothing on turn 1 either way.
- Practical implication for a transfer-heavy fleet: give the `App` a `ContextCacheConfig()` (defaults
  are sane) as soon as you have `sub_agents` + transfers, purely to silence the warning and get the perf
  benefit — no other code changes needed.

---

## 7. `adk` CLI `[pkg-verified: cli/cli_tools_click.py]`

### `adk web [AGENTS_DIR]`
Dev UI + API server together. Key flags (all via decorators `feature_options()` + `fast_api_common_options()` + `web_options()` + `adk_services_options()`):
```
--host 127.0.0.1        --port 8000
--allow_origins ORIGIN  (repeatable; also 'regex:<pattern>')
--reload/--no-reload    (default: reload ON; forced OFF on Windows — "not supported... forces
                          Uvicorn SelectorEventLoop, no subprocess support")
--a2a                   enable A2A endpoint (default OFF)
--reload_agents         live-reload on agent code changes (default OFF)
--trace_to_cloud        DEPRECATED in favor of --otel_to_cloud
--otel_to_cloud         write OTel to Cloud Trace + Cloud Logging
--eval_storage_uri gs://<bucket>
--extra_plugins module.ClassOrInstance  (repeatable)
--url_prefix /some/prefix    (must start with '/', for reverse-proxy mounting)
--trigger_sources pubsub,eventarc   (comma-separated; registers /apps/{app}/trigger/*)
--session_service_uri URI    (see below — 'memory://' | 'sqlite://path' | 'agentengine://<id>' | SQLAlchemy URL)
--artifact_service_uri URI   ('gs://bucket' | 'memory://' | 'file://path')
--memory_service_uri URI     ('rag://<corpus_id>' | 'agentengine://<id>' | 'memory://')
--use_local_storage/--no_use_local_storage   (default True; mutually exclusive with the *_uri flags above)
--default_llm_model MODEL_ID
--logo-text TEXT   --logo-image-url URL
```
`AGENTS_DIR` positional arg, defaults to cwd. Each subdirectory under it is treated as one agent
(needs `agent.py` / `__init__.py` / `root_agent.yaml`), OR point it directly at a single agent folder.

### `adk api_server [AGENTS_DIR]`
Same `fast_api_common_options()` + `adk_services_options()` as `web`, **minus the UI-specific flags**,
plus:
```
--auto_create_session     auto-create a session on first /run if missing (default OFF)
--with_ui                 also serve the Dev UI (default OFF — pure API otherwise)
--gemini_enterprise_app_name NAME
--express_mode             (requires --gemini_enterprise_app_name)
```
Docstring warns explicitly: **"This server's endpoints are unauthenticated. Run it on a trusted network
only... before exposing it to untrusted or public networks."** Runs uvicorn directly in-process
(`uvicorn.Server(config).run()`), not via subprocess.

### `--session_service_uri` value formats (shared by web/api_server/deploy) `[pkg-verified: cli_tools_click.py ~L740]`
```
memory://                          in-memory (default when *_uri unset and --use_local_storage handles the rest)
sqlite://<path_to_sqlite_file>
agentengine://<agent_engine>       full resource name OR bare numeric id
<any SQLAlchemy backend URL>       e.g. postgresql+asyncpg://user:pass@host/db  — see SQLAlchemy engine docs
```
For our stack: **`DatabaseSessionService`** is constructed directly in Python (not via this URI flag) —
`from google.adk.sessions import DatabaseSessionService; DatabaseSessionService(db_url=...)`. The CLI
`--session_service_uri` flag is the equivalent knob when launching via `adk web`/`api_server` instead of
your own `Runner`-driving script.

### `adk deploy cloud_run AGENT_DIR`
```
--project PROJECT           (required; else default gcloud project)
--region REGION              (required; else gcloud prompts interactively — bad for CI, always pass it)
--service_name NAME          (default: 'adk-default-service-name' — ALWAYS override this)
--app_name NAME               (default: the agent's source folder name)
--port 8000
--trace_to_cloud / --otel_to_cloud
--with_ui                    WARNING in help text: "for development and testing only — do not use in production"
--temp_folder PATH           (default: timestamped folder under system temp — where the generated Dockerfile lands)
--log_level LEVEL
--adk_version VERSION        (default: installed dev version, i.e. 2.7.1 for us — pins the ADK version baked into the deployed image)
--a2a
--with_cloud_run_sandbox     requires 'gcloud beta run deploy' release track
--trigger_sources pubsub,eventarc
--allow_origins ORIGIN       (repeatable)
--session_service_uri / --artifact_service_uri / --memory_service_uri / --use_local_storage
                              (adk_services_options(default_use_local_storage=False) — Cloud Run defaults to
                               NOT using local storage, unlike web/api_server)
AGENT (positional)           path to the agent source directory
```
Command has `context_settings={"allow_extra_args": True}` — extra args after `--` pass straight to the
underlying `gcloud run deploy` invocation.

**Known project gotcha (per CLAUDE.md, not re-verified from source this pass):** `adk deploy cloud_run`
can exit 0 even on a failed deploy — always verify with `gcloud run services describe` / hit the
deployed URL, don't trust the CLI exit code alone (rule 02: verify deploy took effect).

**Generated Dockerfile gotcha (per CLAUDE.md):** the default generated Dockerfile installs `google-adk`
without the `[db]` extra required for `DatabaseSessionService`'s Postgres driver — a `requirements.txt`
in the agent source dir (alongside `agent.py`) is honored and merged/overrides the generated
requirements, so pin `google-adk[db]==2.7.1` (or whatever extras you need) there rather than relying on
the CLI-generated default.

### `--a2a` flag (web / api_server / deploy cloud_run) `[pkg-verified]`
Boolean flag, default `False`, present identically on all three commands. Enables the **A2A (Agent2Agent)
protocol endpoint** on the FastAPI app (routing lives in `cli/dev_server.py`/`fast_api.py` — not
individually inspected this pass; flag plumbing confirmed only). Combine with `mode='task'` root agents
per the `run_async` docstring note in §3 ("a direct `run_async` caller reads [output] off the event
stream, and the server-side `A2aAgentExecutor` wrapper turns it into an A2A artifact").

---

## 8. REST API surface (`adk web` / `api_server`) `[pkg-verified: cli/api_server.py]`

Base path is root (no `/api` prefix). All routes below are on the FastAPI `app` object built by
`get_fast_api_app()` (`cli/fast_api.py`) — `dev_server.py` adds additional `/dev/*` debug-only routes
when `web=True`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/version` | ADK version |
| GET | `/list-apps` | discover agent dirs |
| GET | `/apps/{app_name}/app-info` | root agent name/description/sub-agent tree (`AppInfo`) |
| GET | `/apps/{app_name}/users/{user_id}/sessions` | list sessions |
| GET | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | get one session |
| POST | `/apps/{app_name}/users/{user_id}/sessions` | create session, body = `CreateSessionRequest` |
| POST | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | **DEPRECATED** create-with-id variant |
| PATCH | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | update session state w/o running the agent, body = `UpdateSessionRequest` |
| DELETE | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | delete session |
| PATCH | `/apps/{app_name}/users/{user_id}/memory` | update memory |
| POST | `/run` | run agent, **buffered** — returns `list[Event]` (`response_model_exclude_none=True`) |
| POST | `/run_sse` | run agent, **streaming** — `StreamingResponse` of SSE `Event` chunks |
| WS | `/run_live` | bidirectional live/voice session |
| POST | `/agent-identity/finalize` | `FinalizeAgentIdentityCredentialsRequest` |

### `RunAgentRequest` body (both `/run` and `/run_sse`) `[pkg-verified: api_server.py L521]`
```python
{
  "app_name": "foreman",                 # optional if ADK_DEFAULT_APP_NAME env is set
  "user_id": "u1",
  "session_id": "s1",
  "new_message": {"role": "user", "parts": [{"text": "..."}]},   # types.Content
  "streaming": false,                    # /run_sse only: true = actual token streaming, false = one chunk per final turn
  "state_delta": {"k": "v"},             # optional direct session-state patch applied with this turn
  "function_call_event_id": "...",       # OAuth/long-running-tool resume
  "invocation_id": "...",                # resume an interrupted invocation
  "custom_metadata": {"any": "json"}     # becomes RunConfig(custom_metadata=...)
}
```
### `CreateSessionRequest` body `[pkg-verified: api_server.py L535]`
```python
{
  "session_id": "s1",       # optional, random if omitted
  "state": {"k": "v"},      # optional initial state
  "events": [ ... ]         # optional Event[] to seed history — validated to reject client-forged
                             # ADK-protocol function calls (transfer_to_agent-style reserved names)
}
```
`/run` also supports client-disconnect cancellation: it spawns the runner as an `asyncio.Task` alongside
a `request.receive()` monitor loop, and cancels the run if the HTTP client disconnects mid-stream — the
handler returns HTTP `499` on a genuine client-side disconnect. `/run_sse` pre-validates the session
exists (via `session_service.get_session`) **before** starting the SSE stream, unless
`runner.auto_create_session` is set — otherwise 404s eagerly instead of failing mid-stream.

---

## 9. DatabaseSessionService (used by us) `[UNVERIFIED-vs-live-docs — not opened this pass, cite existing project gotchas]`
Per project CLAUDE.md (already verified in earlier sessions, not re-derived here): construct directly
with an asyncpg-style URL, requires the `[db]` extra installed in the deploy image (see §7 Dockerfile
gotcha). Confirm exact constructor signature (`db_url` kwarg name, sync-vs-async engine requirements)
against `.venv/.../google/adk/sessions/database_session_service.py` before wiring — not read in this
pass, flagging as a follow-up rather than asserting from memory (rule 16).

---

## 10. Open items / not verified this pass
- Live `google.github.io/adk-docs` fetch **failed twice** (timeout) — everything above is
  package-source-only, cross-checked against installed 2.7.1, not against the hosted docs prose. Good
  enough per rule 27 (code as ground truth) but re-fetch docs if a narrative/rationale gap shows up.
- `A2A` endpoint's actual route paths/payload shape not enumerated (only the enabling flag confirmed).
- `DatabaseSessionService` constructor not read this pass (see §9).
- Exact JSON shape ADK returns for `output_schema`-constrained final replies (vs. tool-call turns) not
  traced through `base_llm_flow.py` this pass.
- `RunConfig` full field list (only `custom_metadata` and implied `get_session_config`,
  `streaming_mode` seen in context) not enumerated — check `agents/run_config.py` if you need
  streaming-mode control beyond `/run_sse`'s `streaming: bool`.
