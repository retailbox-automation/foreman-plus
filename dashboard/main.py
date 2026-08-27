"""Foreman+ dashboard — public demo console.

Serves the demo page, a read-only /api/state aggregating Postgres (system of
record: journal, facts, agents) + Firestore (live activity), and ONE guarded
write path: POST /api/demo/run, which drives a fixed demo intake through the
real fleet (foreman-hello) so a judge can watch the gate approve/reject live.
The demo trigger is rate-limited (one at a time, cooldown, daily cap) and its
input is hardcoded server-side — the public page cannot feed the LLM.
"""
import asyncio
import base64
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

try:  # container: foreman_core is vendored next to main.py at deploy time
    from foreman_core.closeout import (
        authorization_json, build_closeout,
        render_decider_html, render_homeowner_html,
    )
    from foreman_core.memory import MemoryStore
except ImportError:  # local dev / tests: repo root on sys.path
    from foreman_app.foreman_core.closeout import (
        authorization_json, build_closeout,
        render_decider_html, render_homeowner_html,
    )
    from foreman_app.foreman_core.memory import MemoryStore

try:
    from workspace import group_properties, property_detail, job_detail   # container
except ImportError:
    from dashboard.workspace import group_properties, property_detail, job_detail

STATIC = Path(__file__).parent / "static"

state: dict = {"pool": None, "fs": None}


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads,
                              schema="pg_catalog")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pool"] = await asyncpg.create_pool(
        os.environ["FOREMAN_DB_URL"], init=_init_conn, min_size=1, max_size=4)
    try:
        from google.cloud.firestore_v1.async_client import AsyncClient
        state["fs"] = AsyncClient(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", "foreman-hackathon"))
    except Exception:
        state["fs"] = None
    yield
    await state["pool"].close()


app = FastAPI(lifespan=lifespan)
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/state")
async def api_state():
    pool = state["pool"]
    async with pool.acquire() as conn:
        agents = [dict(r) for r in await conn.fetch(
            "SELECT name, version, description, registered_at FROM agents ORDER BY name")]
        # the public ledger hides infrastructure-outage rejections (verifier
        # unreachable during early billing setup) — they read as breakage, not
        # judgment; the journal itself keeps them, fail-closed by design
        journal = [dict(r) for r in await conn.fetch(
            """SELECT id, proposed_by, proposal, verdict, verifier_model, reason,
                      decided_at, created_at
               FROM gate_journal
               WHERE reason IS NULL OR reason NOT LIKE 'verifier error:%'
               ORDER BY id DESC LIMIT 80""")]
        facts = [dict(r) for r in await conn.fetch(
            """SELECT subject, predicate, object, source_agent, valid_from
               FROM memory_facts WHERE valid_to IS NULL
               ORDER BY subject, id DESC LIMIT 400""")]
        counters = dict((await conn.fetchrow(
            """SELECT count(*) FILTER (WHERE verdict='approved') AS approved,
                      count(*) FILTER (WHERE verdict='rejected') AS rejected,
                      count(*) AS total FROM gate_journal
               WHERE reason IS NULL OR reason NOT LIKE 'verifier error:%'""")))

    jobs: dict[str, list] = {}
    for f in facts:
        jobs.setdefault(f["subject"], []).append({
            "predicate": f["predicate"],
            "value": f["object"].get("value") if isinstance(f["object"], dict) else f["object"],
            "agent": f["source_agent"],
        })

    async def _activity():
        rows = []
        from google.cloud import firestore
        q = (state["fs"].collection("activity")
             .order_by("ts", direction=firestore.Query.DESCENDING).limit(40))
        async for d in q.stream():
            e = d.to_dict()
            ts = e.get("ts")
            rows.append({
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "agent": e.get("agent"), "verdict": e.get("verdict"),
                "subject": e.get("subject"), "predicate": e.get("predicate"),
                "reason": e.get("reason"),
            })
        return rows

    activity = []
    if state["fs"] is not None:
        try:
            # best-effort by contract: a slow/unauthed Firestore must never
            # hang the whole state endpoint (observed: infinite gRPC stall)
            activity = await asyncio.wait_for(_activity(), timeout=3.0)
        except Exception:
            activity = []

    def _row(j):
        p = j["proposal"] if isinstance(j["proposal"], dict) else {}
        return {
            "id": j["id"], "agent": j["proposed_by"], "verdict": j["verdict"],
            "subject": p.get("subject"), "predicate": p.get("predicate"),
            "value": (p.get("object") or {}).get("value"),
            "reason": j["reason"], "model": j["verifier_model"],
            "decided_at": j["decided_at"].isoformat() if j["decided_at"] else None,
        }

    return JSONResponse({
        "agents": [{"name": a["name"], "version": a["version"],
                    "description": a["description"]} for a in agents],
        "journal": [_row(j) for j in journal],
        "jobs": [{"subject": s, "facts": fs} for s, fs in jobs.items()],
        "activity": activity,
        "counters": {k: int(v) for k, v in counters.items()},
    })


async def _facts_and_journal():
    async with state["pool"].acquire() as conn:
        facts = [dict(r) for r in await conn.fetch(
            """SELECT id, subject, predicate, object, source_agent, valid_from, valid_to, ingested_at
               FROM memory_facts WHERE valid_to IS NULL ORDER BY id""")]
        journal = [dict(r) for r in await conn.fetch(
            """SELECT id, proposed_by, proposal, verdict, verifier_model, reason, decided_at, created_at
               FROM gate_journal ORDER BY id""")]
        counters = dict(await conn.fetchrow(
            """SELECT count(*) FILTER (WHERE verdict='approved') AS approved,
                      count(*) FILTER (WHERE verdict='rejected') AS rejected, count(*) AS total
               FROM gate_journal WHERE reason IS NULL OR reason NOT LIKE 'verifier error:%'"""))
    return facts, journal, {k: int(v) for k, v in counters.items()}


@app.get("/api/properties")
async def api_properties():
    facts, journal, counters = await _facts_and_journal()
    props = group_properties(facts, journal)
    with_prop = {j for p in props for j in p["jobs"]}
    all_jobs = {f["subject"].split(":", 1)[-1] for f in facts}
    return JSONResponse({"properties": props, "counters": counters,
                         "no_property_jobs": len(all_jobs - with_prop)})


@app.get("/api/property/{prop_id}")
async def api_property(prop_id: str):
    facts, journal, _ = await _facts_and_journal()
    d = property_detail(prop_id, facts, journal)
    if d is None:
        return JSONResponse({"error": "unknown property"}, status_code=404)
    return JSONResponse(d)


async def _similar(store: MemoryStore, job_id: str, facts: list[dict]) -> list[dict]:
    issue = next((f["object"].get("value") for f in facts
                  if f["subject"] == f"job:{job_id}" and f["predicate"] == "issue"), None)
    if not issue:
        return []
    try:
        try:
            from foreman_core.embedder import GeminiEmbedder
        except ImportError:
            from foreman_app.foreman_core.embedder import GeminiEmbedder
        qvec = await asyncio.wait_for(GeminiEmbedder().embed(str(issue), kind="query"), timeout=3.0)
        hits = await asyncio.wait_for(store.recall(qvec, top_k=6), timeout=3.0)
        return [{"job_id": h["subject"].split(":", 1)[-1], "predicate": h["predicate"],
                 "value": h["object"].get("value"), "score": round(h["score"], 2)}
                for h in hits if h["subject"] != f"job:{job_id}"][:3]
    except Exception:
        return []


@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    facts, journal, _ = await _facts_and_journal()
    store = MemoryStore(state["pool"])
    try:
        closeout = await build_closeout(store, job_id)
    except Exception:
        closeout = None
    d = job_detail(job_id, facts, journal, closeout)
    d["similar"] = await _similar(store, job_id, facts)
    return JSONResponse(d)


@app.get("/doc/{job_id}")
async def job_document(job_id: str, mode: str = "homeowner"):
    """Client-facing closeout document, built strictly from gated memory."""
    store = MemoryStore(state["pool"])
    c = await build_closeout(store, job_id)
    render = render_decider_html if mode == "decider" else render_homeowner_html
    return HTMLResponse(render(c))


@app.get("/api/closeout/{job_id}")
async def closeout_api(job_id: str):
    """Authorization JSON (home-warranty lane / downstream systems)."""
    store = MemoryStore(state["pool"])
    c = await build_closeout(store, job_id)
    return JSONResponse(authorization_json(c))


# ---------------------------------------------------------------- demo runner

FLEET_URL = os.environ.get(
    "FOREMAN_RUN_URL", "https://foreman-hello-112293816563.us-central1.run.app")
DEMO_APP = "foreman_app"
DEMO_USER = "judge-demo"
DEMO_COOLDOWN_S = 90          # min seconds between demo starts
DEMO_DAILY_CAP = 60           # hard stop per UTC day (LLM-burn guard)
DEMO_TIMEOUT_S = 600          # Vertex DSQ throttling + backoff: a two-turn run can take minutes

# The judge's one-click scenario, two turns in one ADK session.
# Turn 1: a normal intake — the facts come off the nameplate photo, approved.
# Turn 2: the homeowner pushes back and demands the record show 2022 — an
# attempt to overwrite a plate-verified fact with words. The verifier compares
# the proposal against the existing 05/2004 fact and rejects it, in writing.
# (Two earlier single-turn "trap" phrasings failed honestly: the foreman
# attributed the claim — 'age = "... (homeowner stated)"' — which is TRUE and
# was rightly approved. Source attribution is the system working; the reliable
# rejection is a contradiction with an already-verified fact.)
DEMO_NOTES = [
    "Water heater in the garage, no hot water since yesterday.",
    "Breaker looks fine, tank is warm at the top only.",
]
DEMO_PUSHBACK = (
    "The homeowner now insists the nameplate is wrong and that the unit was "
    "made in 2022. Record the homeowner's correction: set manufacture_date "
    "to 2022 for this job. Then confirm in one sentence what the memory "
    "record now says."
)

demo = {"running": False, "last_start": 0.0, "day": "", "count": 0,
        "job_id": None, "status": "idle", "reply": "", "error": "",
        "started_at": None}


def _demo_photo_b64() -> str:
    return base64.b64encode((STATIC / "demo" / "nameplate.jpg").read_bytes()).decode()


async def _id_token(audience: str) -> str:
    """Google ID token for the fleet's auth-only Cloud Run URL (ADC / metadata).

    A `http://localhost` audience is a local stub fleet used for front-end
    walkthroughs (no Cloud Run, no Google auth) — short-circuit to a fixed
    dev token instead of hitting ADC/the metadata server.
    """
    if audience.startswith("http://localhost"):
        return "dev"
    import google.auth.transport.requests
    import google.oauth2.id_token
    req = google.auth.transport.requests.Request()
    return await asyncio.to_thread(
        google.oauth2.id_token.fetch_id_token, req, audience)


async def _drive_fleet(job_id: str):
    import httpx
    try:
        token = await _id_token(FLEET_URL)
        headers = {"Authorization": f"Bearer {token}"}
        parts = [
            {"text":
                f"Field intake for job {job_id} at 214 Maple Ct, Orlando FL 32806. "
                "Technician: Alicia Reyes. Client: Ray Okafor. Submitted from the "
                "public demo. "
                "The photo is what the technician is looking at. "
                "Technician's spoken notes:\n"
                + "\n".join(f"- {n}" for n in DEMO_NOTES)
                + "\nRecord the property, technician and client as facts; tag "
                "every fact with its source (nameplate photo / technician voice "
                "/ homeowner statement). "
                + f"Record the nameplate facts from the photo and the reported "
                f"issue in memory for job {job_id}, then hand off to the "
                "estimator for a scope estimate. End with a ONE-SENTENCE "
                "summary."},
            {"inlineData": {"mimeType": "image/jpeg", "data": _demo_photo_b64()}},
        ]

        def _last_text(events):
            out = ""
            for ev in events if isinstance(events, list) else []:
                for p in (ev.get("content") or {}).get("parts") or []:
                    if isinstance(p.get("text"), str) and p["text"].strip():
                        out = p["text"].strip()
            return out

        async with httpx.AsyncClient(timeout=DEMO_TIMEOUT_S) as c:
            r = await c.post(
                f"{FLEET_URL}/apps/{DEMO_APP}/users/{DEMO_USER}/sessions/{job_id}",
                json={}, headers=headers)
            if r.status_code not in (200, 400, 409):
                r.raise_for_status()
            r = await c.post(f"{FLEET_URL}/run", headers=headers, json={
                "app_name": DEMO_APP, "user_id": DEMO_USER,
                "session_id": job_id,
                "new_message": {"role": "user", "parts": parts}})
            r.raise_for_status()
            reply = _last_text(r.json())
            # turn 2: the pushback — an attempt to overwrite a verified fact
            demo.update(status="pushback")
            r = await c.post(f"{FLEET_URL}/run", headers=headers, json={
                "app_name": DEMO_APP, "user_id": DEMO_USER,
                "session_id": job_id,
                "new_message": {"role": "user",
                                "parts": [{"text": DEMO_PUSHBACK}]}})
            r.raise_for_status()
            reply = _last_text(r.json()) or reply
        demo.update(status="done", reply=reply[:600])
    except Exception as e:  # surface, never crash the dashboard
        demo.update(status="error", error=str(e)[:300])
    finally:
        demo["running"] = False


@app.post("/api/demo/run")
async def demo_run():
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if demo["day"] != day:
        demo.update(day=day, count=0)
    if demo["running"]:
        return JSONResponse({"ok": False, "why": "a demo run is already in flight — watch the ledger"},
                            status_code=429)
    if now - demo["last_start"] < DEMO_COOLDOWN_S:
        wait = int(DEMO_COOLDOWN_S - (now - demo["last_start"]))
        return JSONResponse({"ok": False, "why": f"cooldown — try again in {wait}s"},
                            status_code=429)
    if demo["count"] >= DEMO_DAILY_CAP:
        return JSONResponse({"ok": False, "why": "daily demo cap reached"}, status_code=429)

    job_id = "J-DEMO-" + time.strftime("%H%M%S", time.gmtime(now))
    demo.update(running=True, last_start=now, count=demo["count"] + 1,
                job_id=job_id, status="running", reply="", error="",
                started_at=now)
    asyncio.get_running_loop().create_task(_drive_fleet(job_id))
    return {"ok": True, "job_id": job_id}


@app.get("/api/demo/status")
async def demo_status():
    elapsed = int(time.time() - demo["started_at"]) if demo["started_at"] else None
    return {"job_id": demo["job_id"], "status": demo["status"],
            "reply": demo["reply"], "error": demo["error"], "elapsed": elapsed}


# ------------------------------------------------------------ phone intake

from fastapi import File, Form, UploadFile  # noqa: E402

INTAKE_COOLDOWN_S = 30
INTAKE_DAILY_CAP = 60
INTAKE_MAX_BYTES = 12 * 1024 * 1024
intake = {"last_start": 0.0, "day": "", "count": 0, "jobs": {}}


def _intake_text(job_id: str, prop: str, tech: str, client: str, notes: str, has_audio: bool) -> str:
    return (f"Field intake for job {job_id} at {prop}. Technician: {tech}. "
            + (f"Client: {client}. " if client else "")
            + "Submitted from the technician's phone. The photo is the equipment nameplate "
            "or the equipment itself. "
            + ("The audio is the technician's spoken notes — transcribe it and treat it as "
               "the technician's voice. " if has_audio else "")
            + (f"Typed notes: {notes} " if notes else "")
            + "Record the property, technician and client as facts. Record every nameplate "
            "field you can read with source \"nameplate photo\"; if a field is unreadable, "
            "record it as UNKNOWN with source \"plate unreadable\". Record the reported issue "
            "and observations with source \"technician voice\"; anything attributed to the "
            "homeowner with source \"homeowner statement\". Then hand off to the estimator "
            "for a scope estimate. End with a ONE-SENTENCE summary for the technician.")


async def _drive_intake(job_id: str, parts: list[dict]):
    import httpx
    st = intake["jobs"][job_id]
    try:
        token = await _id_token(FLEET_URL)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=DEMO_TIMEOUT_S) as c:
            r = await c.post(f"{FLEET_URL}/apps/{DEMO_APP}/users/tech/sessions/{job_id}",
                             json={}, headers=headers)
            if r.status_code not in (200, 400, 409):
                r.raise_for_status()
            r = await c.post(f"{FLEET_URL}/run", headers=headers, json={
                "app_name": DEMO_APP, "user_id": "tech", "session_id": job_id,
                "new_message": {"role": "user", "parts": parts}})
            r.raise_for_status()
            reply = ""
            for ev in r.json() if isinstance(r.json(), list) else []:
                for p in (ev.get("content") or {}).get("parts") or []:
                    if isinstance(p.get("text"), str) and p["text"].strip():
                        reply = p["text"].strip()
        st.update(status="done", reply=reply[:600])
    except Exception as e:
        st.update(status="error", error=str(e)[:300])


@app.post("/api/intake")
async def intake_submit(property: str = Form(...), technician: str = Form(...),
                        client: str = Form(""), notes: str = Form(""),
                        photo: UploadFile = File(...), audio: UploadFile | None = File(None)):
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if intake["day"] != day:
        intake.update(day=day, count=0)
    if now - intake["last_start"] < INTAKE_COOLDOWN_S:
        return JSONResponse({"ok": False, "why": f"cooldown — try again in {int(INTAKE_COOLDOWN_S - (now - intake['last_start']))}s"}, status_code=429)
    if intake["count"] >= INTAKE_DAILY_CAP:
        return JSONResponse({"ok": False, "why": "daily intake cap reached"}, status_code=429)
    photo_bytes = await photo.read()
    if not photo_bytes or len(photo_bytes) > INTAKE_MAX_BYTES:
        return JSONResponse({"ok": False, "why": "photo missing or too large"}, status_code=422)
    audio_bytes = await audio.read() if audio is not None else b""
    if len(audio_bytes) > INTAKE_MAX_BYTES:
        return JSONResponse({"ok": False, "why": "audio too large"}, status_code=422)
    job_id = "J-T-" + time.strftime("%H%M%S", time.gmtime(now))
    parts = [{"text": _intake_text(job_id, property.strip(), technician.strip(), client.strip(),
                                    notes.strip(), bool(audio_bytes))},
             {"inlineData": {"mimeType": photo.content_type or "image/jpeg",
                             "data": base64.b64encode(photo_bytes).decode()}}]
    if audio_bytes:
        parts.append({"inlineData": {"mimeType": (audio.content_type or "audio/webm").split(";")[0],
                                     "data": base64.b64encode(audio_bytes).decode()}})
    intake.update(last_start=now, count=intake["count"] + 1)
    intake["jobs"][job_id] = {"status": "running", "reply": "", "error": "", "started_at": now,
                              "property": property.strip()}
    asyncio.get_running_loop().create_task(_drive_intake(job_id, parts))
    return {"ok": True, "job_id": job_id}


@app.get("/api/intake/status")
async def intake_status(job_id: str):
    st = intake["jobs"].get(job_id)
    if not st:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    async with state["pool"].acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM memory_facts WHERE subject=$1 AND valid_to IS NULL",
                                f"job:{job_id}")
    return {"job_id": job_id, "status": st["status"], "elapsed": int(time.time() - st["started_at"]),
            "reply": st["reply"], "error": st["error"], "facts": int(n), "property": st["property"]}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    """Office seat: the contractor's workspace (properties → record → job → ledger)."""
    return FileResponse(STATIC / "app" / "index.html")


@app.get("/tech")
async def tech():
    """Technician seat: pre-visit briefing → photo + voice capture → result."""
    return FileResponse(STATIC / "tech" / "index.html")


@app.get("/ops")
async def ops():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/#/ledger", status_code=302)
