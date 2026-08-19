"""Agent-facing memory tools: thin, non-raising wrappers over store+gate."""
import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Verdict
from foreman_app.foreman_core.tools import make_memory_tools

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="ok")


class RejectAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=False, reason="contradicts record")


@pytest_asyncio.fixture
async def env():
    pool = await create_pool(DB_URL)
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE")
    await apply_schema(pool)
    store = MemoryStore(pool)
    await store.register_agent("intake", version="0.1")
    yield store
    await pool.close()


@pytest.mark.asyncio
async def test_write_then_search_roundtrip(env):
    write, search = make_memory_tools("intake", env, WriteGate(env, ApproveAll()))
    res = await write(subject="job:1", predicate="equipment_model", value="Rheem 82V40-2")
    assert res["verdict"] == "approved"

    found = await search(subject="job:1")
    assert found["facts"] == [
        {"predicate": "equipment_model", "value": "Rheem 82V40-2", "source_agent": "intake"}
    ]


@pytest.mark.asyncio
async def test_rejected_write_reports_reason_and_writes_nothing(env):
    write, search = make_memory_tools("intake", env, WriteGate(env, RejectAll()))
    res = await write(subject="job:1", predicate="install_year", value=2030)
    assert res["verdict"] == "rejected"
    assert "contradicts" in res["reason"]
    assert (await search(subject="job:1"))["facts"] == []
