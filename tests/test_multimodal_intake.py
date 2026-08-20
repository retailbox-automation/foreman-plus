"""SPIKE 3 as a test (live): photo+voice through the ADK Runner into gated memory.

The riskiest unverified integration point (docs/stack/INDEX.md): multimodal parts
in `new_message` must survive the fleet (tool calls, transfer) AND persist through
DatabaseSessionService into Postgres.

Key assert: equipment model/serial land in memory FROM THE PHOTO — the text
message never names them.

Run: pytest tests/test_multimodal_intake.py -m integration
"""
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() not in ("1", "true", "yes"):
    # legacy key path (prepay-billed); Vertex mode uses ADC from .env instead
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
os.environ["FOREMAN_DB_URL"] = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import DatabaseSessionService  # noqa: E402
from google.genai import types  # noqa: E402

from foreman_app.agent import root_agent  # noqa: E402
from foreman_app import runtime  # noqa: E402

SESSIONS_DB = "postgresql+asyncpg://oskolamicheal@localhost:5432/foreman_core_test"


@pytest_asyncio.fixture
async def store():
    s, _ = await runtime.get_env()
    async with s.pool.acquire() as conn:
        await conn.execute("TRUNCATE memory_facts, gate_journal RESTART IDENTITY CASCADE")
    yield s


@pytest.mark.asyncio
async def test_photo_and_voice_reach_memory_through_fleet(store):
    photo = (ROOT / "spikes/assets/nameplate.jpg").read_bytes()
    voice = (ROOT / "spikes/assets/voice-note.aiff").read_bytes()

    session_id = f"mm-{uuid.uuid4().hex[:8]}"
    svc = DatabaseSessionService(db_url=SESSIONS_DB)
    await svc.create_session(app_name="mm", user_id="u", session_id=session_id)
    runner = Runner(agent=root_agent, app_name="mm", session_service=svc)

    msg = types.Content(role="user", parts=[
        types.Part(text=(
            "Job J-MM1: intake attached — a photo of the unit and its nameplate, "
            "plus the tech's voice note. Extract the facts and give me the scope."
        )),
        types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=photo)),
        types.Part(inline_data=types.Blob(mime_type="audio/aiff", data=voice)),
    ])

    final = ""
    async for event in runner.run_async(user_id="u", session_id=session_id, new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)

    facts = await store.current_facts("job:J-MM1")
    by_pred = {f["predicate"]: str(f["object"].get("value", "")) for f in facts}

    # from the PHOTO (never present in the text). OCR of one plate char varies
    # between runs (82V40-2 vs 82VH40-2) — assert the stable parts of the model
    # and the serial, which pins the source to the nameplate unambiguously.
    import re
    assert any(re.search(r"82V.?40", v) for v in by_pred.values()), \
        f"nameplate model not read: {by_pred}"
    assert any("0504B01826" in v.replace(" ", "") for v in by_pred.values()), \
        f"nameplate serial not read: {by_pred}"
    # from the VOICE (never present in the text)
    joined = " ".join(by_pred.values()).lower()
    assert "valve" in joined or "drip" in joined or "leak" in joined, \
        f"voice complaint not captured: {by_pred}"

    # session (with the binary parts) survived persistence: fresh service re-reads it
    svc2 = DatabaseSessionService(db_url=SESSIONS_DB)
    sess = await svc2.get_session(app_name="mm", user_id="u", session_id=session_id)
    assert sess is not None and len(sess.events) >= 2
    assert final, "no final response"
