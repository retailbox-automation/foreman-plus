"""Workspace API: /api/properties, /api/property/{id}, /api/job/{id} — and the
office/tech seat routes (/, /tech). Runs against local Postgres db
foreman_core_test_b (see FOREMAN_TEST_DB_URL / DB_URL below).
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

DB_URL = os.environ.get("FOREMAN_TEST_DB_URL",
                        "postgresql://oskolamicheal@localhost:5432/foreman_core_test")
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
        await conn.execute("DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE")
    await apply_schema(pool)
    s = MemoryStore(pool)
    await s.register_agent("foreman", version="0.1", description="test")
    await s.register_agent("estimator", version="0.1", description="test")
    gate = WriteGate(s, verifier=ApproveAll())
    for pred, value, src in [
        ("property", "214 Maple Ct, Orlando FL 32806", "intake"),
        ("technician", "Alicia Reyes", "intake"), ("client", "Ray Okafor", "intake"),
        ("equipment_model", "Rheem 82V40-2", "nameplate photo"),
        ("manufacture_date", "05/2004", "nameplate photo"),
        ("serial_number", "UNKNOWN", "plate unreadable"),
        ("issue", "no hot water since yesterday", "technician voice"),
    ]:
        await gate.submit(Proposal(subject="job:J-W1", predicate=pred,
                                   object={"value": value, "source": src}, proposed_by="foreman"))
    await gate.submit(Proposal(subject="job:J-W1", predicate="estimate",
                               object={"value": json.dumps({"job": "J-W1", "hours": 2, "parts": ["thermostat"]}), "source": "estimator"},
                               proposed_by="estimator"))
    await gate.submit(Proposal(subject="job:J-ORPHAN", predicate="issue", object={"value": "no property"}, proposed_by="foreman"))
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_properties_property_and_job_endpoints(seeded):
    dm = load_dashboard()
    async with dm.app.router.lifespan_context(dm.app):
        async with AsyncClient(transport=ASGITransport(app=dm.app), base_url="http://t") as c:
            r = await c.get("/api/properties"); assert r.status_code == 200
            body = r.json()
            assert [p["id"] for p in body["properties"]] == ["214-maple-ct-orlando-fl-32806"]
            assert body["properties"][0]["state"] == "unknowns"
            assert body["no_property_jobs"] == 1
            r = await c.get("/api/property/214-maple-ct-orlando-fl-32806"); assert r.status_code == 200
            d = r.json()
            assert d["property"]["client"] == "Ray Okafor"
            assert any(q["kind"] == "unknown" for q in d["open_questions"])
            assert d["auto_passed"] == 8
            assert all(b["gate_entry_id"] for b in d["briefing"])
            r = await c.get("/api/property/nope"); assert r.status_code == 404
            r = await c.get("/api/job/J-W1"); assert r.status_code == 200
            j = r.json()
            assert j["property"]["id"] == "214-maple-ct-orlando-fl-32806"
            assert j["facts"]["money"][0]["value"] == "2 h · thermostat"
            assert all(isinstance(m["value"], str) for m in j["facts"]["money"])
            assert isinstance(j["similar"], list)
            r = await c.get("/"); assert r.status_code == 200 and "Foreman+" in r.text
            r = await c.get("/tech"); assert r.status_code == 200
