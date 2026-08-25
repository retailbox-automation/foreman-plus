"""Closer agent wiring: the fleet's third agent + its closeout tool.

Runs against local Postgres db `foreman_core_test`.
"""
import json

import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict
from foreman_app.foreman_core.tools import make_closeout_tool

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="fake: ok")


@pytest_asyncio.fixture
async def store():
    pool = await create_pool(DB_URL)
    async with pool.acquire() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE"
        )
    await apply_schema(pool)
    s = MemoryStore(pool)
    await s.register_agent("foreman", version="0.1", description="test")
    yield s
    await pool.close()


@pytest.mark.asyncio
async def test_closeout_tool_returns_document_url_and_compact_summary(store):
    gate = WriteGate(store, verifier=ApproveAll())
    for pred, value in {
        "equipment_model": "Rheem 82V40-2",
        "estimate": json.dumps({"job": "J-T1", "hours": 2, "parts": ["thermostat"]}),
    }.items():
        await gate.submit(Proposal(subject="job:J-T1", predicate=pred,
                                   object={"value": value}, proposed_by="foreman"))

    close_out_job = make_closeout_tool(store)
    result = await close_out_job(job_id="J-T1")

    assert result["document_url"].endswith("/doc/J-T1")
    assert result["verified"]["equipment_model"] == "Rheem 82V40-2"
    assert "serial_number" in result["unknowns"]
    assert result["authorization"]["type"] == "authorization_request"
    # tool never raises — errors come back as a dict
    bad = await close_out_job(job_id="NO-SUCH-JOB")
    assert "error" not in bad  # empty job is a valid (all-unknown) closeout


def test_fleet_has_closer_agent_with_closeout_tool():
    from foreman_app.agent import root_agent, closer
    from foreman_app import runtime

    names = [a.name for a in root_agent.sub_agents]
    assert "closer" in names
    tool_names = [t.__name__ for t in closer.tools]
    assert "close_out_job" in tool_names
    assert "lookup_facts" in tool_names
    # closer is a registered fleet identity (gate rejects unknown agents)
    assert any(name == "closer" for name, _ in runtime.FLEET)
