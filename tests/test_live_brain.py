"""Unit tests for live_brain — no network, fake session objects."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_brain.brain import BrainConfig, LatestFrame, LiveBrain
from live_brain.sources import latest_jpeg


def make_brain(tool_executor=None) -> LiveBrain:
    return LiveBrain(BrainConfig(project="test-project", tool_executor=tool_executor),
                     client=object())


# ---------------------------------------------------------------- LatestFrame
def test_latest_frame_fresh_once():
    f = LatestFrame()
    assert f.take_fresh() is None
    f.set(b"jpeg1")
    assert f.take_fresh() == b"jpeg1"
    assert f.take_fresh() is None  # already consumed
    f.set(b"jpeg2")
    assert f.take_fresh() == b"jpeg2"


def test_latest_frame_ignores_empty():
    f = LatestFrame()
    f.set(b"")
    assert f.take_fresh() is None


# ------------------------------------------------------------ message handling
def msg(text=None, turn_complete=False, handle=None, go_away=False):
    return SimpleNamespace(
        text=text,
        server_content=SimpleNamespace(turn_complete=turn_complete) if turn_complete or text else None,
        session_resumption_update=SimpleNamespace(resumable=True, new_handle=handle) if handle else None,
        go_away=SimpleNamespace(time_left=1) if go_away else None,
    )


def test_handle_message_assembles_turn():
    brain = make_brain()
    loop = asyncio.new_event_loop()
    try:
        brain._pending = loop.create_future()
        brain._handle_message(msg(text="Hel"))
        brain._handle_message(msg(text="lo."))
        brain._handle_message(msg(turn_complete=True))
        assert brain._pending.result() == "Hello."
    finally:
        loop.close()


def test_handle_message_captures_resumption_and_goaway():
    brain = make_brain()
    brain._handle_message(msg(handle="h-123"))
    assert brain._resumption_handle == "h-123"
    assert brain._connect_config().session_resumption.handle == "h-123"
    assert not brain._goaway
    brain._handle_message(msg(go_away=True))
    assert brain._goaway


# ------------------------------------------------------------------------ ask
class FakeSession:
    def __init__(self, brain: LiveBrain, reply: str):
        self.brain = brain
        self.reply = reply
        self.sent: list[tuple[str, object]] = []

    async def send_realtime_input(self, media=None, **kw):
        self.sent.append(("frame", media))

    async def send_client_content(self, turns=None, **kw):
        self.sent.append(("text", turns))
        # simulate the server answering asynchronously
        async def answer():
            self.brain._handle_message(msg(text=self.reply))
            self.brain._handle_message(msg(turn_complete=True))
        asyncio.get_running_loop().create_task(answer())


@pytest.mark.asyncio
async def test_ask_puts_the_frame_inside_the_question_turn():
    brain = make_brain()
    fake = FakeSession(brain, "Turn the valve clockwise.")
    brain._session = fake
    brain._connected.set()
    brain.push_frame(b"frame-bytes")
    reply = await brain.ask("what now?")
    assert reply == "Turn the valve clockwise."
    kinds = [k for k, _ in fake.sent]
    assert kinds == ["text"]  # never a separate realtime frame send in ask()
    parts = fake.sent[0][1].parts
    assert parts[0].inline_data.data == b"frame-bytes" and parts[1].text == "what now?"
    # second ask: the same (recent) frame still rides along — the tech is still
    # looking at the same thing
    await brain.ask("and now?")
    assert len(fake.sent[1][1].parts) == 2


@pytest.mark.asyncio
async def test_ask_without_any_frame_carries_a_no_photo_system_marker():
    """Persona alone did not stop hallucination (live 25.08: 'Camera, buddy' →
    invented valve); a frameless turn must carry an explicit SYSTEM marker."""
    brain = make_brain()
    fake = FakeSession(brain, "Point the camera at the unit.")
    brain._session = fake
    brain._connected.set()
    await brain.ask("what is this?")
    parts = fake.sent[0][1].parts
    assert len(parts) == 1
    assert parts[0].text.startswith("[SYSTEM: no photo is attached")
    assert "no photo at all" in parts[0].text
    assert parts[0].text.rstrip().endswith("User: what is this?")


@pytest.mark.asyncio
async def test_ask_when_disconnected_times_out():
    brain = make_brain()
    brain.cfg.ask_timeout_s = 0.05
    with pytest.raises(asyncio.TimeoutError):
        await brain.ask("anyone there?")


# ------------------------------------------------------------ native tool calls
class FakeToolSession:
    """Session for the tool-call path: records tool responses and content."""
    def __init__(self):
        self.tool_responses = []
        self.sent = []

    async def send_tool_response(self, function_responses=None):
        self.tool_responses.append(function_responses)

    async def send_client_content(self, turns=None, **kw):
        self.sent.append(turns)


def tool_msg(name="take_photo", call_id="c1"):
    fc = SimpleNamespace(name=name, args={}, id=call_id)
    return SimpleNamespace(text=None, server_content=None, session_resumption_update=None,
                           go_away=None, tool_call=SimpleNamespace(function_calls=[fc]))


@pytest.mark.asyncio
async def test_tool_call_executes_and_responds():
    ran = []
    async def executor(name, args):
        ran.append(name)
        return {"ok": True}
    brain = make_brain(tool_executor=executor)
    fake = FakeToolSession()
    brain._session = fake
    brain._handle_message(tool_msg())
    await asyncio.sleep(0)  # let the created task run
    await asyncio.sleep(0)
    assert ran == ["take_photo"]
    assert brain.tool_ran == "take_photo"
    fr = fake.tool_responses[0][0]
    assert fr.name == "take_photo" and fr.response == {"ok": True}


@pytest.mark.asyncio
async def test_tool_executor_failure_is_reported_not_raised():
    async def executor(name, args):
        raise RuntimeError("bridge down")
    brain = make_brain(tool_executor=executor)
    fake = FakeToolSession()
    brain._session = fake
    brain._handle_message(tool_msg())
    for _ in range(3):
        await asyncio.sleep(0)
    fr = fake.tool_responses[0][0]
    assert fr.response["ok"] is False and "bridge down" in fr.response["error"]


@pytest.mark.asyncio
async def test_tool_call_ignored_without_executor():
    brain = make_brain()
    fake = FakeToolSession()
    brain._session = fake
    brain._handle_message(tool_msg())
    await asyncio.sleep(0)
    assert fake.tool_responses == []


@pytest.mark.asyncio
async def test_tool_turn_protocol_holds_the_pending_ask():
    """Live completes the tool-REQUEST turn empty; the answer comes in a NEW
    turn after tool_response. The empty completion must not resolve ask()."""
    async def executor(name, args):
        return {"ok": True}
    brain = make_brain(tool_executor=executor)
    brain._session = FakeToolSession()
    brain._pending = asyncio.get_running_loop().create_future()
    brain._handle_message(tool_msg())                 # model requests the tool
    brain._handle_message(msg(turn_complete=True))    # empty tool-request turn
    assert not brain._pending.done()                  # ask still waiting
    brain._handle_message(msg(text="I see a breaker panel."))
    brain._handle_message(msg(turn_complete=True))    # real answer turn
    assert brain._pending.result() == "I see a breaker panel."
    await asyncio.sleep(0)  # drain the executor task


# -------------------------------------------------------------------- sources
def test_latest_jpeg_picks_newest(tmp_path: Path):
    assert latest_jpeg(tmp_path) is None
    (tmp_path / "a.jpg").write_bytes(b"old")
    import os
    os.utime(tmp_path / "a.jpg", (1, 1))
    (tmp_path / "b.jpg").write_bytes(b"new")
    data, _ = latest_jpeg(tmp_path)
    assert data == b"new"
    assert latest_jpeg(tmp_path / "missing") is None
