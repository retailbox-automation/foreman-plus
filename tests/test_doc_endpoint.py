"""Dashboard document endpoints: /doc/{job} (homeowner + decider) and
/api/closeout/{job} (authorization JSON) — the judge-clickable exit of a job.

Runs against local Postgres db `foreman_core_test`.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"
REPO = Path(__file__).resolve().parents[1]


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="fake: ok")


def load_dashboard():
    os.environ["FOREMAN_DB_URL"] = DB_URL
    spec = importlib.util.spec_from_file_location(
        "dashboard_main", REPO / "dashboard" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def seeded():
    pool = await create_pool(DB_URL)
    async with pool.acquire() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE")
    await apply_schema(pool)
    s = MemoryStore(pool)
    await s.register_agent("foreman", version="0.1", description="test")
    gate = WriteGate(s, verifier=ApproveAll())
    for pred, value in {
        "equipment_model": "Rheem 82V40-2",
        "manufacture_date": "05/2004",
        "estimate": json.dumps({"job": "J-D1", "hours": 2, "parts": ["thermostat"]}),
    }.items():
        await gate.submit(Proposal(subject="job:J-D1", predicate=pred,
                                   object={"value": value}, proposed_by="foreman"))
    yield
    await pool.close()


@pytest.mark.asyncio
async def test_doc_endpoints_serve_all_three_renders(seeded):
    dm = load_dashboard()
    async with dm.lifespan(dm.app):
        transport = ASGITransport(app=dm.app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/doc/J-D1")
            assert r.status_code == 200
            assert "Rheem 82V40-2" in r.text
            assert "advisory" in r.text.lower()

            r2 = await client.get("/doc/J-D1", params={"mode": "decider"})
            assert r2.status_code == 200
            assert "decision-maker" in r2.text.lower()

            r3 = await client.get("/api/closeout/J-D1")
            assert r3.status_code == 200
            body = r3.json()
            assert body["type"] == "authorization_request"
            assert body["verified_facts"]["equipment_model"]["value"] == "Rheem 82V40-2"
