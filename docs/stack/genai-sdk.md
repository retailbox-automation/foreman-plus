# google-genai Python SDK — cheatsheet (Foreman+)

Installed: **google-genai 2.18.1**, **google-adk 2.7.1** (verified via
`.venv/bin/pip show`, this repo's `.venv`, 2026-08-19). Source verified by reading
`.venv/lib/python3.14/site-packages/google/genai/{_api_client.py,client.py,types.py,models.py,errors.py}`.
Docs verified live via WebFetch on ai.google.dev (2026-08-19), URLs inline.

---

## 1. Client routing: Gemini API vs Vertex/Enterprise

`genai.Client(...)` picks ONE of two backends. Decision lives in
`_api_client.py::BaseApiClient.__init__` (line ~641). **Verbatim mechanism:**

```python
self.vertexai = vertexai   # explicit kwarg, default None
if self.vertexai is None:
    env_enterprise = os.environ.get('GOOGLE_GENAI_USE_ENTERPRISE')  # "true"/"1"
    env_vertexai   = os.environ.get('GOOGLE_GENAI_USE_VERTEXAI')     # "true"/"1"
    # GOOGLE_GENAI_USE_ENTERPRISE wins if both set with conflicting values
    self.vertexai = env_enterprise if env_enterprise is not None else env_vertexai
```

- **No hidden auto-detection by API key prefix.** `google-genai` itself never
  inspects the key string to decide the backend — it is 100% driven by the
  `vertexai`/`enterprise` kwarg or the two env vars above. If a project sees
  "AQ key routes to Vertex on GCP", the actual cause is one of: (a)
  `GOOGLE_GENAI_USE_VERTEXAI=true` present in the Cloud Run service env / `.env`
  loaded by ADK's `env_utils.py`, or (b) ADK/adk-cli scaffolding template sets it.
  **Grep for it explicitly before blaming the SDK: `env | grep VERTEXAI`.**
- `project`/`location` kwargs (or `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`
  env vars) are **only valid when `vertexai=True`** — passing them with
  `vertexai` falsy raises `ValueError('Gemini API does not support project/location.')`.
- **Gemini Developer API path** (what Foreman+ uses): `vertexai` falsy →
  requires `api_key` (explicit or via env) → `base_url = https://generativelanguage.googleapis.com/`,
  `api_version = v1beta`. **No project/location needed at all.**
- **Enterprise/Vertex path**: `base_url` becomes
  `https://{location}-aiplatform.googleapis.com/` (or the aiplatform.googleapis.com
  global endpoint when `location` resolves to `"global"`), `api_version = v1beta1`.

### API key precedence (env vars)
```python
def get_env_api_key():
    env_google_api_key = os.environ.get('GOOGLE_API_KEY')
    env_gemini_api_key = os.environ.get('GEMINI_API_KEY')
    # if BOTH set → GOOGLE_API_KEY wins, logs a warning
    return env_google_api_key or env_gemini_api_key or None
```
Explicit `api_key=` kwarg to `Client()` always beats both env vars.
Source: `_api_client.py` lines 128-141. Confirmed against docs
(ai.google.dev/gemini-api/docs/api-key): *"If both are set, GOOGLE_API_KEY
takes precedence."*

### `AQ.` vs `AIza` key formats — CONFIRMED (docs, not SDK)
`google-genai` treats every key as an opaque bearer string (just strips
whitespace, sets `x-goog-api-key` header) — the SDK does not branch on prefix.
The **distinction is a Google Cloud concept, not an SDK one**:
- **`AIza...`** = "standard" API key — tied to a project for billing/quota, not
  bound to an identity.
- **`AQ....`** = "authorization key" — **bound directly to a Google Cloud
  service account**, giving per-identity access control + fast leaked-key
  revocation. This is what Foreman+'s `gemini-foreman-spike` key is
  (bound to `foreman-agent@` SA).
- Either format works for `Client(api_key=...)` on the Gemini Developer API
  endpoint as long as `vertexai` is not forced true. Keys can be scoped
  in AI Studio to "Restrict to Gemini API only" — **do this**, it's the
  mechanism that blocks the key from also hitting the Vertex surface.
- Source: https://ai.google.dev/gemini-api/docs/api-key (WebFetch 2026-08-19).

### Recommended pin for Foreman+ (Cloud Run, bound-SA `AQ.` key)
```python
client = genai.Client(
    api_key=os.environ["GOOGLE_API_KEY"],
    vertexai=False,           # explicit — do not rely on env absence
)
```
and make sure the Cloud Run service does **not** carry
`GOOGLE_GENAI_USE_VERTEXAI=true` / `GOOGLE_GENAI_USE_ENTERPRISE=true` in its
env (`gcloud run services describe foreman-hello --format='value(spec.template.spec.containers[0].env)'`).

---

## 2. Client construction + async (`.aio`) surface

```python
from google import genai
from google.genai import types

client = genai.Client(api_key="AQ....", vertexai=False)

# sync
resp = client.models.generate_content(model="gemini-3.6-flash", contents="hi")

# async — mirrors sync 1:1 under client.aio
resp = await client.aio.models.generate_content(
    model="gemini-3.6-flash",
    contents="hi",
    config=types.GenerateContentConfig(temperature=0.2),
)

# streaming (async)
async for chunk in await client.aio.models.generate_content_stream(
    model="gemini-3.6-flash", contents="hi"
):
    print(chunk.text, end="")
```
Signatures (verified `models.py` lines 8628, 8840, 9465):
```python
async def generate_content(self, *, model: str, contents: ContentListUnion|Dict,
                            config: GenerateContentConfigOrDict | None = None) -> GenerateContentResponse
async def generate_content_stream(self, *, model, contents, config=None) -> AsyncIterator[GenerateContentResponse]
async def embed_content(self, *, model: str, contents: ContentListUnion|Dict,
                         config: EmbedContentConfigOrDict | None = None) -> EmbedContentResponse
```
All keyword-only (`*`) after `self`. `config` accepts either a `types.X` object
or a plain dict (SDK does `types.GenerateContentConfig(**config)` when it's a dict).

---

## 3. `GenerateContentConfig` — fields that matter for Foreman+

(Full field list: `types.py` line 6392, ~35 fields total.) Selected:

| Field | Type | Notes |
|---|---|---|
| `system_instruction` | `ContentUnion` (str/Content/list) | steering prompt |
| `temperature`, `top_p`, `top_k`, `seed` | float/int | sampling |
| `max_output_tokens` | int | hard cap on output |
| `stop_sequences` | `list[str]` | |
| `response_mime_type` | `str` | `"application/json"` for structured output |
| `response_schema` | `SchemaUnion` = `dict \| type \| Schema \| GenericAlias \| UnionType` | **pass a pydantic `BaseModel` class directly** — SDK converts it; requires `response_mime_type="application/json"` |
| `response_json_schema` | `Any` | alternative to `response_schema` accepting a raw JSON-Schema dict (use if `response_schema` doesn't render your schema correctly) |
| `tools` | `ToolListUnion` | function-calling / built-in tools (google_search, code_execution, url_context, google_maps…) |
| `tool_config` | `ToolConfig` | forces/limits tool calls |
| `safety_settings` | `list[SafetySetting]` | |
| `thinking_config` | `ThinkingConfig` | see §4 |
| `media_resolution` | `MediaResolution` | per-request image/video token budget |
| `http_options` | `HttpOptions` | per-call override incl. `retry_options`, `timeout` |
| `cached_content` | `str` | context-cache resource name |
| `automatic_function_calling` | `AutomaticFunctionCallingConfig` | AFC on/off, max remote calls |
| `labels` | `dict[str,str]` | request labels (Vertex/Enterprise) |

### Structured output example (pydantic)
```python
from pydantic import BaseModel

class ScopeItem(BaseModel):
    device: str
    problem: str
    urgency: str

resp = await client.aio.models.generate_content(
    model="gemini-3.6-flash",
    contents=[image_part, audio_part, "Extract repair scope."],
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ScopeItem,          # or list[ScopeItem]
    ),
)
scope = ScopeItem.model_validate_json(resp.text)
```

---

## 4. Thinking config (Gemini 3.x)

`types.ThinkingConfig` (types.py line 5676):
```python
class ThinkingConfig:
    include_thoughts: bool | None   # return thought summaries in response
    thinking_budget: int | None     # tokens; 0 = DISABLED, -1 = AUTOMATIC
    thinking_level: ThinkingLevel | None  # MINIMAL | LOW | MEDIUM | HIGH
```
`ThinkingLevel` enum values (types.py line 364):
`THINKING_LEVEL_UNSPECIFIED, MINIMAL, LOW, MEDIUM, HIGH`.

Per Google docs (ai.google.dev/gemini-api/docs/thinking, WebFetch 2026-08-19):
- **gemini-3.6-flash**: thinking **on by default**, default level **MEDIUM**; supports all 4 levels.
- **gemini-3.5-flash-lite**: thinking **on by default**, default level **MINIMAL**; supports all 4 levels.
- `thinking_level` is the Gemini-3.x knob (replaces the older `thinking_budget`-only
  interface from 2.5 models — both fields exist on the type, `thinking_level` is
  the intended one for 3.x).
- **Multi-turn / function-calling with thought signatures:**
  - *Stateful mode* (`store=True` + `previous_interaction_id`) — server manages
    thought blocks/signatures automatically, nothing to resend. **This is the
    ADK-friendly default** since ADK's `DatabaseSessionService` already persists
    turn history.
  - *Stateless mode* (manually replaying `contents` each turn, which is what a
    raw `generate_content` loop without `store` does) — you **MUST resend every
    `thought` part verbatim**, including tool-call thought signatures, or the
    model loses reasoning continuity. UNVERIFIED whether ADK's own agent loop
    does this automatically for `google_llm.py` — check `models/google_llm.py`
    before assuming.

```python
config = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level="LOW", include_thoughts=False),
)
```

---

## 5. Multimodal input — inline bytes vs Files API

### `types.Part` construction (types.py ~2225-2470)
```python
types.Part.from_text(text="...")
types.Part.from_bytes(data: bytes, mime_type: str, media_resolution=None)   # inline
types.Part.from_uri(file_uri: str, mime_type: str | None = None)            # Files API / GCS
types.Part.from_function_call(name, args) / from_function_response(name, response)
```
`Blob` (inline) fields: `data: bytes`, `mime_type: str`, `display_name: str | None`.
`FileData` (URI-based) fields: `file_uri: str`, `mime_type: str | None`.

```python
photo_part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")
audio_part = types.Part.from_bytes(data=ogg_bytes, mime_type="audio/ogg")

resp = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=[photo_part, audio_part, "Read the nameplate and transcribe the complaint."],
)
```

### Size / format limits (ai.google.dev, WebFetch 2026-08-19)
| Constraint | Value | Source |
|---|---|---|
| Inline request total size (prompt + all inline bytes) | **20 MB** — beyond this, use Files API | `/gemini-api/docs/image-understanding`, `/gemini-api/docs/audio` |
| Files API max file size | **2 GB** per file | `/gemini-api/docs/files` |
| Files API total storage per project | **20 GB** | same |
| Files API retention | **48 hours**, then auto-deleted | same |
| Max images per request | **3,600** | `/gemini-api/docs/image-understanding` |
| Image mime types | `image/png, image/jpeg, image/webp, image/heic, image/heif` | same |
| Image tokenization | ≤384×384px → 258 tokens flat; larger → tiled 768×768 @ 258 tokens/tile | same |
| Audio mime types | `audio/wav, audio/mp3, audio/aiff, audio/aac, audio/ogg, audio/flac` | `/gemini-api/docs/audio` |
| Max audio length per prompt | **9.5 hours** | same |
| Audio token rate | **32 tokens/sec** (1 min ≈ 1,920 tokens) | same |

### Files API upload
```python
myfile = client.files.upload(file="path/to/sample.mp3")
# returns object with .uri, .mime_type — use via Part.from_uri(file_uri=myfile.uri, mime_type=myfile.mime_type)
```
Async variant: `await client.aio.files.upload(...)` — UNVERIFIED exact async
signature parity beyond what sync doc shows; grep `files.py` before relying on
kwargs beyond `file=`.

**Foreman+ spike result (verified live, 2026-08-18):** one
`gemini-3.5-flash generate_content` call with photo+audio parts →
structured scope in **14.9s** on free tier; vision correctly read a
water-heater nameplate (model/serial/date). See
`docs/SPIKE-2026-08-18-multimodal.md`.

---

## 6. Embeddings

Model names live at ai.google.dev/gemini-api/docs/models (WebFetch 2026-08-19):
- **`gemini-embedding-001`** — text-only embeddings. Paid: **$0.15 / 1M input
  tokens**, free tier available. Output dims: UNVERIFIED exact default (docs
  page didn't render the dims table) — Google's published default for this
  model family is 3072 with `output_dimensionality` truncation down to smaller
  sizes (768/1536/3072 commonly cited) — **verify at call time**, don't hardcode.
- **`gemini-embedding-2-preview`** — multimodal embeddings (text/image/audio/video).
  Paid: text $0.20, image $0.45, audio $6.50, video $12.00 per 1M tokens (preview pricing).

```python
resp = await client.aio.models.embed_content(
    model="gemini-embedding-001",
    contents=["repair note text"],
    config={"output_dimensionality": 768, "task_type": "RETRIEVAL_DOCUMENT"},
)
vec = resp.embeddings[0].values
```
`EmbedContentConfig` fields (types.py line 8886): `task_type: str | None`,
`title: str | None` (only for `RETRIEVAL_DOCUMENT`), `output_dimensionality: int | None`,
plus Vertex/Enterprise-only: `mime_type`, `auto_truncate`, `document_ocr`,
`audio_track_extraction`. **`task_type` is a free string, not an SDK enum** in
this package — Google's documented values (per public Gemini docs, not
re-verified live this pass): `RETRIEVAL_QUERY`, `RETRIEVAL_DOCUMENT`,
`SEMANTIC_SIMILARITY`, `CLASSIFICATION`, `CLUSTERING`, `QUESTION_ANSWERING`,
`FACT_VERIFICATION`, `CODE_RETRIEVAL_QUERY`. UNVERIFIED live this pass — cross
check `ai.google.dev/gemini-api/docs/embeddings` before shipping pgvector code.

Routing note (`models.py` line ~9465): on the **Gemini Developer API**
(`vertexai=False`, our path), `embed_content` always calls the plain
`embedContent` endpoint — the Vertex-only branching (`t_is_vertex_embed_content_model`,
`PREDICT` vs `EMBED_CONTENT` API type split) never triggers for us. One caveat
baked into the SDK: for `gemini-embedding-2*` models specifically, `contents`
gets normalized via `t.t_contents()` even on the Gemini API path — harmless for
list-of-strings input.

---

## 7. Context window / output caps (verified live, ai.google.dev, 2026-08-19)

| Model | Input token limit | Output token limit | Thinking default |
|---|---|---|---|
| **gemini-3.6-flash** | 1,048,576 | 65,536 | ON, level=MEDIUM |
| **gemini-3.5-flash-lite** | 1,048,576 | 65,536 | ON, level=MINIMAL |
| gemini-3.7-flash (exists, "complex coding/agentic") | UNVERIFIED (not fetched this pass) | UNVERIFIED | UNVERIFIED |
| gemini-3.5-flash | UNVERIFIED (not fetched this pass — listed in model index) | UNVERIFIED | UNVERIFIED |

Both verified models support: caching, code execution, computer use (preview),
file search, function calling, Google Maps grounding, search grounding,
structured outputs, thinking, URL context. Neither supports image/audio
*generation* output or Live API. Knowledge cutoff: **not published** on either
model page as fetched — do not assert a cutoff date without re-checking.

### Free tier / Tier 1 RPM/TPM/RPD — UNVERIFIED (numeric)
Google **no longer publishes a static rate-limit table** on
`/gemini-api/docs/rate-limits` — the page explicitly says *"Rate limits depend
on a variety of factors (such as your usage tier) and can be viewed in Google
AI Studio"* and links to `https://aistudio.google.com/rate-limit` (a live
per-account dashboard, not fetchable via WebFetch — needs an authenticated
browser session). **Action: check that URL logged in as `oskola7@gmail.com`
in chrome-qa (:9224) for Foreman+'s actual current RPM/TPM/RPD**, don't guess.
What IS published (pricing page, spend-based tiers):
- **Tier 1**: billing account linked, **$250/month spend cap**, "$10 over a
  10-minute window" spend-based rate limit mentioned.
- **Tier 2**: $100 paid + 3 days, **$2,000 cap**.
- **Tier 3**: $1,000 paid + 30 days, **$20,000–$100,000+ cap**.
- Free tier: input/output free of charge for gemini-3.6-flash and
  gemini-3.5-flash-lite (both explicitly listed "Free of charge" on pricing page).

### Pricing (paid tier, per 1M tokens — verified live, ai.google.dev/gemini-api/docs/pricing)
| Model | Input | Output | Context cache | Cache storage |
|---|---|---|---|---|
| gemini-3.6-flash | $0.75 (→ $1.50 from 2027-01-01) | $3.75 (→ $7.50) | $0.075 (→ $0.15) | $0.50/1M tok/hr (→ $1.00) |
| gemini-3.5-flash-lite | $0.30 | $2.50 | $0.03 | $1.00/1M tok/hr |
| gemini-embedding-001 | $0.15 | — | — | — |
| gemini-embedding-2-preview | $0.20 text / $0.45 image / $6.50 audio / $12.00 video | — | — | — |
Batch API = ~50% off input+output on gemini-3.6-flash; batch also cheaper on flash-lite ($0.15 in / $1.25 out).

---

## 8. Error taxonomy + retry patterns

`errors.py` — verified class hierarchy:
```python
class APIError(Exception):          # base; has .code (int), .status (str), .message (str)
class ClientError(APIError): ...    # 4xx
class ServerError(APIError): ...    # 5xx
class UnknownFunctionCallArgumentError(ValueError)
class UnsupportedFunctionError(ValueError)
class FunctionInvocationError(ValueError)
class UnknownApiResponseError(ValueError)
```
Catch pattern:
```python
from google.genai import errors
try:
    resp = client.models.generate_content(...)
except errors.ClientError as e:
    # e.code, e.status, e.message — 4xx: bad request, 429 quota, 403 permission
    ...
except errors.ServerError as e:
    # 5xx — safe to retry with backoff
    ...
```

### Built-in retry: `types.HttpRetryOptions` (types.py line 2560)
```python
class HttpRetryOptions:
    attempts: int | None        # default 5 (0 or 1 = no retries)
    initial_delay: float | None # default 1.0s
    max_delay: float | None     # default 60.0s
    exp_base: float | None      # default 2.0 (exponential backoff multiplier)
    jitter: float | None        # default 1.0
    http_status_codes: list[int] | None  # default retryable set = 408, 429, 5xx
```
Set globally via `Client(http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=8)))`
or per-call via `GenerateContentConfig(http_options=...)`. The SDK's own
`tenacity`-based retry wraps every HTTP call — **you generally don't need your
own retry loop for 429/5xx**, just tune `HttpRetryOptions`. Do add your own
handling for `ClientError` codes that mean "fix the request" (400 invalid
arg, 403 permission/key-scope, 404 model not found) — those aren't retryable.

---

## Open items / UNVERIFIED — do not ship on these without a live check
1. **Numeric RPM/TPM/RPD for Foreman+'s actual tier** — not published statically
   by Google anymore; must be read from the authenticated AI Studio rate-limit
   dashboard (`aistudio.google.com/rate-limit`) under `oskola7@gmail.com`.
2. **gemini-3.7-flash and gemini-3.5-flash context/output caps** — not fetched
   this pass (only 3.6-flash and 3.5-flash-lite were pulled from their model pages).
3. **Knowledge cutoff dates** for 3.6-flash / 3.5-flash-lite — not published on
   the model spec pages as rendered.
4. **`gemini-embedding-001` default output dimensionality** — the model page's
   dims table didn't render through WebFetch; confirm before hardcoding a
   pgvector column width.
5. **Embedding `task_type` enum values** — listed from general Gemini API
   knowledge, not re-verified live against `ai.google.dev/gemini-api/docs/embeddings`
   this pass.
6. **Whether ADK's `models/google_llm.py` handles stateless thought-signature
   resend automatically** — flagged, not read this pass; check before relying
   on multi-turn thinking continuity outside ADK's session service.
7. **`client.aio.files.upload` exact kwargs** beyond `file=` — not read from
   `files.py` this pass.
