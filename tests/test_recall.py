"""Semantic recall layer: embeddings on approved facts + nearest-neighbour search."""
import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"
DIM = 768


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="ok")


def vec(axis: int) -> list[float]:
    v = [0.0] * DIM
    v[axis] = 1.0
    return v


class FakeEmbedder:
    """Maps texts containing a keyword to a fixed axis; default axis 99."""

    def __init__(self, axes: dict[str, int]):
        self.axes = axes

    async def embed(self, text: str, kind: str = "document") -> list[float]:
        for kw, axis in self.axes.items():
            if kw in text:
                return vec(axis)
        return vec(99)


class CrashingEmbedder:
    async def embed(self, text: str, kind: str = "document") -> list[float]:
        raise RuntimeError("embed endpoint down")


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


def prop(subject, predicate, value):
    return Proposal(subject=subject, predicate=predicate,
                    object={"value": value}, proposed_by="foreman")


@pytest.mark.asyncio
async def test_approved_fact_stores_embedding(store):
    gate = WriteGate(store, verifier=ApproveAll(), embedder=FakeEmbedder({"leak": 1}))
    await gate.submit(prop("job:1", "issue", "leaking drain valve"))
    row = (await store.fact_history("job:1", "issue"))[0]
    assert row["embedding"] is not None


@pytest.mark.asyncio
async def test_embedder_failure_does_not_block_the_write(store):
    gate = WriteGate(store, verifier=ApproveAll(), embedder=CrashingEmbedder())
    entry = await gate.submit(prop("job:1", "issue", "leaking drain valve"))
    assert entry.verdict == "approved"
    row = (await store.fact_history("job:1", "issue"))[0]
    assert row["embedding"] is None  # best-effort: fact lands, embedding backfillable


@pytest.mark.asyncio
async def test_recall_returns_nearest_current_facts(store):
    emb = FakeEmbedder({"leak": 1, "thermostat": 2})
    gate = WriteGate(store, verifier=ApproveAll(), embedder=emb)
    await gate.submit(prop("job:1", "issue", "leaking drain valve"))
    await gate.submit(prop("job:2", "issue", "thermostat misreads temperature"))

    hits = await store.recall(vec(1), top_k=2)
    assert hits[0]["subject"] == "job:1"
    assert hits[0]["score"] > hits[-1]["score"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_gemini_embeddings_semantic_recall(store):
    """gemini-embedding-001 @768 dims: semantically related query finds the fact."""
    import os
    from pathlib import Path
    env_file = Path(__file__).resolve().parent.parent / ".env"
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    from foreman_app.foreman_core.embedder import GeminiEmbedder

    emb = GeminiEmbedder()
    gate = WriteGate(store, verifier=ApproveAll(), embedder=emb)
    await gate.submit(prop("job:old-1", "issue", "water heater dripping from corroded drain valve"))
    await gate.submit(prop("job:old-2", "issue", "garage door opener chain slips, door reverses"))

    qvec = await emb.embed("leaking water heater", kind="query")
    hits = await store.recall(qvec, top_k=2)
    assert hits[0]["subject"] == "job:old-1", f"semantic order wrong: {hits}"


@pytest.mark.asyncio
async def test_recall_ignores_superseded_facts(store):
    emb = FakeEmbedder({"leak": 1, "resolved": 2})
    gate = WriteGate(store, verifier=ApproveAll(), embedder=emb)
    await gate.submit(prop("job:1", "issue", "leaking drain valve"))
    await gate.submit(prop("job:1", "issue", "resolved after valve replacement"))

    hits = await store.recall(vec(1), top_k=5)
    assert all("leaking" not in str(h["object"]) for h in hits), \
        "superseded fact leaked into recall"
