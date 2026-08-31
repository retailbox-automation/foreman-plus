"""Advisory triage of a property's open questions — Gemma 4 on Vertex AI MaaS.

The write-gate stays deterministic and Gemini-verified; Gemma NEVER writes
memory. It only labels what already exists (category + urgency per open
question) so the office can sort a morning's open questions without opening
each one. The split is deliberate: gate = record, Gemma = advisory reading
layer, and the UI says so on the label.

Model: ``google/gemma-4-26b-a4b-it-maas`` — Vertex AI serverless
(Model-as-a-Service). MaaS models are NOT served on the
``publishers/google/models/...:generateContent`` path; they answer only on the
OpenAI-compatible ``endpoints/openapi/chat/completions`` route, and (verified
live 31.08) on the **global** host, not a regional one. Plain ADC — the same
identity the recall embedder already uses; no API key, no deployed endpoint.

Everything here is best-effort by contract: any failure (auth, network, quota,
unparseable output) returns no labels and the page renders exactly as before.
"""
import asyncio
import json
import logging
import os
import re

log = logging.getLogger("foreman.triage")

GEMMA_MODEL = "google/gemma-4-26b-a4b-it-maas"
GEMMA_MODEL_SHORT = "gemma-4-26b-a4b-it"
_URL = ("https://aiplatform.googleapis.com/v1/projects/{project}/locations/"
        "global/endpoints/openapi/chat/completions")

CATEGORIES = ("safety", "dispute", "data-gap", "warranty", "billing")
URGENCY = ("now", "next-visit", "paperwork-only")

_PROMPT = """You label open questions on a field-service property record.
Each line is one open question: either a fact the write-gate REFUSED (a
conflicting claim) or a field recorded as UNKNOWN.

For each numbered item pick exactly one category and one urgency:
categories: safety (gas, electric, scald, refrigerant, structural risk),
dispute (someone contests a recorded value), data-gap (a field is simply
missing), warranty (coverage or registration), billing (money, estimate).
urgency: now (address before/at the next dispatch), next-visit (collect or
settle on the next routine visit), paperwork-only (desk work, no site action).

Answer with STRICT JSON only — an array like
[{"i": 0, "category": "data-gap", "urgency": "next-visit"}]
with one object per item, no prose, no markdown fence.

Items:
{items}"""

# labels survive per instance; an open question's content never changes under
# the same gate entry id, so there is nothing to invalidate
_cache: dict[str, dict] = {}


def _key(q: dict) -> str | None:
    gid = q.get("gate_entry_id")
    if gid is None:
        return None
    return f"{gid}:{q.get('kind')}:{q.get('predicate')}"


def _item_line(i: int, q: dict) -> str:
    if q.get("kind") == "rejected":
        return (f"{i}. REFUSED claim: {q.get('predicate')} = {q.get('proposed')!r}; "
                f"verifier said: {q.get('reason')!r}")
    return f"{i}. UNKNOWN field: {q.get('predicate')} ({q.get('reason') or 'not captured'})"


def parse_labels(text: str, n: int) -> dict[int, dict]:
    """STRICT-ish parse of the model's array. Anything malformed is dropped —
    a missing label is a rendering no-op, never an error."""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return {}
    out: dict[int, dict] = {}
    for entry in arr if isinstance(arr, list) else []:
        if not isinstance(entry, dict):
            continue
        i, cat, urg = entry.get("i"), entry.get("category"), entry.get("urgency")
        if isinstance(i, int) and 0 <= i < n and cat in CATEGORIES and urg in URGENCY:
            out[i] = {"category": cat, "urgency": urg}
    return out


async def _post_vertex(payload: dict) -> dict:
    """Real transport: ADC token → global MaaS endpoint. Sync auth refresh is
    pushed off the event loop."""
    import google.auth
    import google.auth.transport.requests
    import httpx

    def _token() -> str:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    token = await asyncio.to_thread(_token)
    url = _URL.format(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "foreman-hackathon"))
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(url, headers={"Authorization": f"Bearer {token}"},
                         json=payload)
        r.raise_for_status()
        return r.json()


async def triage_open_questions(questions: list[dict], post=None) -> dict:
    """{"model": ..., "labels": {gate_entry_id-key: {category, urgency}}}.

    ``post`` is injectable for tests; production uses the Vertex transport.
    """
    keyed = [(q, _key(q)) for q in questions]
    todo = [(i, q, k) for i, (q, k) in enumerate(keyed) if k and k not in _cache]
    if todo:
        items = "\n".join(_item_line(j, q) for j, (_, q, _k) in enumerate(todo))
        payload = {
            "model": GEMMA_MODEL,
            "messages": [{"role": "user",
                          "content": _PROMPT.replace("{items}", items)}],
            "max_tokens": 800,
            "temperature": 0.1,
        }
        try:
            body = await (post or _post_vertex)(payload)
            text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
            got = parse_labels(text, len(todo))
            for j, (_, _q, k) in enumerate(todo):
                if j in got:
                    _cache[k] = got[j]
        except Exception as e:  # advisory layer: degrade silently but never silently in the logs
            log.warning("gemma triage unavailable: %r", e)

    labels = {}
    for q, k in keyed:
        if k and k in _cache:
            labels[str(q["gate_entry_id"])] = _cache[k]
    return {"model": GEMMA_MODEL_SHORT, "labels": labels}
