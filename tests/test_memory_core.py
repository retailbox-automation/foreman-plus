"""Core memory tests: bi-temporal facts + write-gate journal.

Runs against local Postgres db `foreman_core_test` (createdb foreman_core_test).
"""
import asyncio
import datetime as dt

import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"


class ApproveAll:
    """Fake verifier: approves everything, records what it saw."""

    def __init__(self):
        self.calls = []

    async def verify(self, proposal, existing_facts):
        self.calls.append((proposal, existing_facts))
        return Verdict(approved=True, reason="fake: ok")


class RejectAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=False, reason="fake: contradiction")


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


def prop(subject="equipment:wh-1", predicate="model", obj=None, agent="foreman"):
    return Proposal(
        subject=subject,
        predicate=predicate,
        object=obj or {"value": "Rheem 82V40-2"},
        proposed_by=agent,
    )


@pytest.mark.asyncio
async def test_approved_proposal_writes_fact_with_provenance(store):
    gate = WriteGate(store, verifier=ApproveAll())
    entry = await gate.submit(prop())

    assert entry.verdict == "approved"
    facts = await store.current_facts("equipment:wh-1")
    assert len(facts) == 1
    assert facts[0]["object"] == {"value": "Rheem 82V40-2"}
    # provenance: fact points back to the journal entry that admitted it
    assert facts[0]["gate_entry_id"] == entry.id


@pytest.mark.asyncio
async def test_new_fact_supersedes_prior_same_subject_predicate(store):
    gate = WriteGate(store, verifier=ApproveAll())
    await gate.submit(prop(obj={"value": "Rheem 82V40-2"}))
    await gate.submit(prop(obj={"value": "Rheem PROG50"}))

    current = await store.current_facts("equipment:wh-1")
    assert len(current) == 1
    assert current[0]["object"] == {"value": "Rheem PROG50"}

    history = await store.fact_history("equipment:wh-1", "model")
    assert len(history) == 2
    old = [f for f in history if f["object"]["value"] == "Rheem 82V40-2"][0]
    new = [f for f in history if f["object"]["value"] == "Rheem PROG50"][0]
    assert old["valid_to"] is not None
    assert old["superseded_by"] == new["id"]
    assert new["valid_to"] is None


@pytest.mark.asyncio
async def test_rejected_proposal_writes_nothing_but_journals_reason(store):
    gate = WriteGate(store, verifier=RejectAll())
    entry = await gate.submit(prop())

    assert entry.verdict == "rejected"
    assert "contradiction" in entry.reason
    assert await store.current_facts("equipment:wh-1") == []
    journal = await store.gate_journal(subject="equipment:wh-1")
    assert len(journal) == 1
    assert journal[0]["verdict"] == "rejected"


@pytest.mark.asyncio
async def test_verifier_receives_existing_facts_for_contradiction_check(store):
    approver = ApproveAll()
    gate = WriteGate(store, verifier=approver)
    await gate.submit(prop(obj={"value": "Rheem 82V40-2"}))
    await gate.submit(prop(obj={"value": "Rheem PROG50"}))

    _, existing = approver.calls[1]
    assert len(existing) == 1
    assert existing[0]["object"] == {"value": "Rheem 82V40-2"}


@pytest.mark.asyncio
async def test_as_of_returns_fact_current_at_that_moment(store):
    gate = WriteGate(store, verifier=ApproveAll())
    await gate.submit(prop(obj={"value": "old"}))
    t_between = dt.datetime.now(dt.timezone.utc)
    await asyncio.sleep(0.02)
    await gate.submit(prop(obj={"value": "new"}))

    then = await store.current_facts("equipment:wh-1", as_of=t_between)
    assert [f["object"]["value"] for f in then] == ["old"]
    now = await store.current_facts("equipment:wh-1")
    assert [f["object"]["value"] for f in now] == ["new"]


class Crashing:
    async def verify(self, proposal, existing_facts):
        raise RuntimeError("LLM endpoint down")


@pytest.mark.asyncio
async def test_verifier_crash_fails_closed_rejected_not_raised(store):
    gate = WriteGate(store, verifier=Crashing())
    entry = await gate.submit(prop())

    assert entry.verdict == "rejected"
    assert "verifier error" in entry.reason
    assert await store.current_facts("equipment:wh-1") == []
    journal = await store.gate_journal(subject="equipment:wh-1")
    assert journal[0]["verdict"] == "rejected"


@pytest.mark.asyncio
async def test_unregistered_agent_proposal_is_rejected_without_verifier(store):
    approver = ApproveAll()
    gate = WriteGate(store, verifier=approver)
    entry = await gate.submit(prop(agent="rogue-agent"))

    assert entry.verdict == "rejected"
    assert "not registered" in entry.reason
    assert approver.calls == []  # identity check happens BEFORE the LLM verifier
    assert await store.current_facts("equipment:wh-1") == []
