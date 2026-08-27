"""E2E (live Gemini): the fleet records facts through the write-gate into shared memory.

Run: pytest tests/test_fleet_e2e.py -m integration
"""
import os
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

env_file = Path(__file__).resolve().parent.parent / ".env"
for line in env_file.read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() not in ("1", "true", "yes"):
    # legacy key path (prepay-billed); Vertex mode uses ADC from .env instead
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
os.environ.setdefault("FOREMAN_DB_URL",
                       "postgresql://oskolamicheal@localhost:5432/foreman_core_test")

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from foreman_app.agent import root_agent  # noqa: E402
from foreman_app import runtime  # noqa: E402


@pytest_asyncio.fixture
async def clean_db():
    store, _ = await runtime.get_env()
    async with store.pool.acquire() as conn:
        await conn.execute("TRUNCATE memory_facts, gate_journal RESTART IDENTITY CASCADE")
    yield store


@pytest.mark.asyncio
async def test_fleet_records_reported_facts_via_gate(clean_db):
    store = clean_db
    svc = InMemorySessionService()
    await svc.create_session(app_name="t", user_id="u", session_id="s1")
    runner = Runner(agent=root_agent, app_name="t", session_service=svc)

    msg = types.Content(role="user", parts=[types.Part(text=(
        "Job J-77: water heater Rheem 82V40-2, serial RH04-556677, manufactured 05/2004, "
        "leaking from the bottom. Give me the scope."
    ))])
    final = ""
    async for event in runner.run_async(user_id="u", session_id="s1", new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)

    facts = await store.current_facts("job:J-77")
    journal = await store.gate_journal(subject="job:J-77")
    approved = [j for j in journal if j["verdict"] == "approved"]

    assert facts, "fleet wrote no facts to shared memory"
    assert approved, "no approved gate entries"
    predicates = {f["predicate"] for f in facts}
    assert "equipment_model" in predicates
    assert final, "no final response"


@pytest.mark.asyncio
async def test_intake_records_property_technician_and_sources(clean_db):
    store = clean_db
    svc = InMemorySessionService()
    await svc.create_session(app_name="t", user_id="u", session_id="s2")
    runner = Runner(agent=root_agent, app_name="t", session_service=svc)

    text = ("Field intake for job J-PROP1 at 214 Maple Ct, Orlando FL 32806. "
            "Technician: Alicia Reyes. Client: Ray Okafor. "
            "Technician's spoken notes:\n- electric water heater in the garage, no hot water since yesterday\n"
            "- the nameplate serial is scratched off, cannot read it\n"
            "Record the property, technician and client as facts, record every nameplate "
            "and reported attribute with its source, then hand off to the estimator.")
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(user_id="u", session_id="s2", new_message=msg):
        pass  # drain to completion; assertions read shared memory directly

    facts = {f["predicate"]: f["object"] for f in await store.current_facts("job:J-PROP1")}
    assert facts["property"]["value"] == "214 Maple Ct, Orlando FL 32806"
    assert facts["technician"]["value"] == "Alicia Reyes"
    assert facts["client"]["value"] == "Ray Okafor"
    assert facts["issue"].get("source") == "technician voice"
    assert facts["serial_number"]["value"] == "UNKNOWN"
    assert facts["serial_number"].get("source") == "plate unreadable"
