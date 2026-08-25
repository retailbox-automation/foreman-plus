"""Foreman+ dashboard — read-only ops console.

Serves the control-room page and a single /api/state endpoint aggregating:
Postgres (system of record: journal, facts, agents) + Firestore (live activity).
No LLM calls, no write paths — safe to expose publicly for the demo.
"""
import json
import os
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


@app.get("/api/state")
async def api_state():
    pool = state["pool"]
    async with pool.acquire() as conn:
        agents = [dict(r) for r in await conn.fetch(
            "SELECT name, version, description, registered_at FROM agents ORDER BY name")]
        journal = [dict(r) for r in await conn.fetch(
            """SELECT id, proposed_by, proposal, verdict, verifier_model, reason,
                      decided_at, created_at
               FROM gate_journal ORDER BY id DESC LIMIT 80""")]
        facts = [dict(r) for r in await conn.fetch(
            """SELECT subject, predicate, object, source_agent, valid_from
               FROM memory_facts WHERE valid_to IS NULL
               ORDER BY subject, id DESC LIMIT 400""")]
        counters = dict((await conn.fetchrow(
            """SELECT count(*) FILTER (WHERE verdict='approved') AS approved,
                      count(*) FILTER (WHERE verdict='rejected') AS rejected,
                      count(*) AS total FROM gate_journal""")))

    jobs: dict[str, list] = {}
    for f in facts:
        jobs.setdefault(f["subject"], []).append({
            "predicate": f["predicate"],
            "value": f["object"].get("value") if isinstance(f["object"], dict) else f["object"],
            "agent": f["source_agent"],
        })

    activity = []
    if state["fs"] is not None:
        try:
            from google.cloud import firestore
            q = (state["fs"].collection("activity")
                 .order_by("ts", direction=firestore.Query.DESCENDING).limit(40))
            async for d in q.stream():
                e = d.to_dict()
                ts = e.get("ts")
                activity.append({
                    "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "agent": e.get("agent"), "verdict": e.get("verdict"),
                    "subject": e.get("subject"), "predicate": e.get("predicate"),
                    "reason": e.get("reason"),
                })
        except Exception:
            pass

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


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
