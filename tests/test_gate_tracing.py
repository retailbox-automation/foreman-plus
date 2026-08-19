"""The write-gate emits its own OTel span so a full trace reads
intake -> LLM -> gate -> DB in Cloud Trace. No provider configured => no-op."""
import pytest
import pytest_asyncio
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="ok")


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


@pytest.mark.asyncio
async def test_submit_emits_gate_span_with_verdict(store):
    exporter.clear()
    gate = WriteGate(store, verifier=ApproveAll())
    await gate.submit(Proposal(subject="job:1", predicate="model",
                               object={"value": "x"}, proposed_by="foreman"))

    spans = [s for s in exporter.get_finished_spans() if s.name == "write_gate.submit"]
    assert spans, "gate span missing"
    attrs = dict(spans[0].attributes)
    assert attrs["foreman.subject"] == "job:1"
    assert attrs["foreman.agent"] == "foreman"
    assert attrs["foreman.verdict"] == "approved"
