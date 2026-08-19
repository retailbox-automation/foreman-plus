"""Activity feed: every gate decision is published for the live dashboard.

Postgres stays the system of record; the feed is best-effort fan-out — a broken
feed must never affect gate semantics.
"""
import os
from pathlib import Path

import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="ok")


class RejectAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=False, reason="no")


class FakeFeed:
    def __init__(self):
        self.events = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class CrashingFeed:
    async def publish(self, event: dict) -> None:
        raise RuntimeError("firestore down")


@pytest_asyncio.fixture
async def store():
    pool = await create_pool(DB_URL)
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE")
    await apply_schema(pool)
    s = MemoryStore(pool)
    await s.register_agent("foreman", version="0.1")
    yield s
    await pool.close()


def prop(value="Rheem 82V40-2"):
    return Proposal(subject="job:1", predicate="model",
                    object={"value": value}, proposed_by="foreman")


@pytest.mark.asyncio
async def test_gate_publishes_approved_and_rejected_decisions(store):
    feed = FakeFeed()
    approved = await WriteGate(store, ApproveAll(), activity=feed).submit(prop())
    rejected = await WriteGate(store, RejectAll(), activity=feed).submit(prop("other"))

    assert [e["verdict"] for e in feed.events] == ["approved", "rejected"]
    e = feed.events[0]
    assert e["type"] == "gate_decision"
    assert e["agent"] == "foreman"
    assert e["subject"] == "job:1"
    assert e["gate_entry_id"] == approved.id
    assert feed.events[1]["gate_entry_id"] == rejected.id


@pytest.mark.asyncio
async def test_broken_feed_never_affects_gate_semantics(store):
    gate = WriteGate(store, ApproveAll(), activity=CrashingFeed())
    entry = await gate.submit(prop())
    assert entry.verdict == "approved"
    assert len(await store.current_facts("job:1")) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_firestore_roundtrip():
    ROOT = Path(__file__).resolve().parent.parent
    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS",
        str(Path.home() / ".gcp-keys/foreman-agent.json"))
    from foreman_app.foreman_core.activity import FirestoreActivityFeed

    feed = FirestoreActivityFeed(project="foreman-hackathon")
    marker = f"test-{os.getpid()}"
    await feed.publish({"type": "gate_decision", "verdict": "approved",
                        "agent": "foreman", "subject": marker,
                        "predicate": "t", "reason": "roundtrip", "gate_entry_id": 0})
    docs = await feed.recent(limit=20)
    assert any(d.get("subject") == marker for d in docs), docs