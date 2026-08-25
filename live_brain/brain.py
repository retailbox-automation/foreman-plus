"""Persistent Gemini Live session (Vertex) that sees frames and answers questions.

Verified against real Vertex behavior in spikes/live_api_probe.py:
TEXT response modality requires model gemini-live-2.5-flash at location=global.
Session lifetime + resumption handles: spikes/live_api_longevity_probe.py.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from google import genai
from google.genai import types

log = logging.getLogger("live_brain")

DEFAULT_MODEL = "gemini-live-2.5-flash"  # TEXT modality: only this one, location=global


@dataclass
class BrainConfig:
    project: str
    location: str = "global"
    model: str = DEFAULT_MODEL
    system_instruction: str = ""
    frame_interval_s: float = 2.0
    ask_timeout_s: float = 25.0
    reconnect_backoff_s: float = 1.0
    # Native tool calling: the executor runs a named tool (e.g. take_photo via
    # the glasses bridge) and returns a JSON-able result dict. None = no tools.
    tool_executor: "ToolExecutor | None" = None


ToolExecutor = Callable[[str, dict], Awaitable[dict]]

TAKE_PHOTO_DECL = types.FunctionDeclaration(
    name="take_photo",
    description=("Capture a fresh photo through the technician's glasses camera. "
                 "Call this whenever you need to SEE what they are looking at — "
                 "they moved, they ask you to look, or your view is stale."),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)


class LatestFrame:
    """Keeps only the newest JPEG; consumers pull at their own pace."""

    def __init__(self) -> None:
        self._data: bytes | None = None
        self._ts: float = 0.0
        self._consumed_ts: float = 0.0

    def set(self, data: bytes, ts: float | None = None) -> None:
        if not data:
            return
        self._data = data
        self._ts = ts if ts is not None else time.monotonic()

    def take_fresh(self) -> bytes | None:
        """Return the frame only if it wasn't consumed yet (avoid re-sending)."""
        if self._data is None or self._ts <= self._consumed_ts:
            return None
        self._consumed_ts = self._ts
        return self._data

    def peek(self, max_age_s: float = 120.0) -> bytes | None:
        """Latest frame even if already consumed — for a question that should
        still see what the tech is looking at (bounded by staleness)."""
        if self._data is None or time.monotonic() - self._ts > max_age_s:
            return None
        return self._data

    @property
    def age_s(self) -> float | None:
        return None if self._data is None else time.monotonic() - self._ts


class LiveBrain:
    """One Live session + reconnect loop. ask() is the only public entry for turns."""

    def __init__(self, config: BrainConfig, client: genai.Client | None = None) -> None:
        self.cfg = config
        self._client = client or genai.Client(
            vertexai=True, project=config.project, location=config.location)
        self.frame = LatestFrame()
        self._session = None
        self._connected = asyncio.Event()
        self._turn_buf: list[str] = []
        self._pending: asyncio.Future[str] | None = None
        self._resumption_handle: str | None = None
        self._goaway = False
        self._turn_lock = asyncio.Lock()
        self._runner_task: asyncio.Task | None = None
        self._stopping = False

    # -- pure-ish message handling (unit-tested with fake messages) ----------
    def _handle_message(self, msg) -> None:
        upd = getattr(msg, "session_resumption_update", None)
        if upd is not None and getattr(upd, "resumable", False):
            handle = getattr(upd, "new_handle", None)
            if handle:
                self._resumption_handle = handle
        if getattr(msg, "go_away", None) is not None:
            self._goaway = True
        tc = getattr(msg, "tool_call", None)
        if tc is not None and self.cfg.tool_executor is not None:
            # Execute off the receive loop; the session keeps flowing.
            asyncio.create_task(self._run_tools(list(tc.function_calls or [])))
        text = getattr(msg, "text", None)
        if text:
            self._turn_buf.append(text)
        sc = getattr(msg, "server_content", None)
        if sc is not None and getattr(sc, "turn_complete", False):
            reply = "".join(self._turn_buf).strip()
            self._turn_buf = []
            if self._pending is not None and not self._pending.done():
                self._pending.set_result(reply)

    async def _run_tools(self, calls) -> None:
        session = self._session
        if session is None:
            return
        responses = []
        for fc in calls:
            name = getattr(fc, "name", "")
            args = dict(getattr(fc, "args", None) or {})
            log.info("tool_call %s(%s)", name, args)
            self.tool_ran = name
            try:
                result = await self.cfg.tool_executor(name, args)  # type: ignore[misc]
            except Exception as e:  # noqa: BLE001 - report failure to the model
                result = {"ok": False, "error": str(e)[:200]}
            responses.append(types.FunctionResponse(
                id=getattr(fc, "id", None), name=name, response=result))
        try:
            await session.send_tool_response(function_responses=responses)
        except Exception as e:  # noqa: BLE001
            log.warning("send_tool_response failed: %s", e)

    #: name of the last tool the model invoked during the current ask (or None)
    tool_ran: str | None = None

    def _connect_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT],
            # Grounding + hands: search the web AND drive its own camera.
            # Mixing GoogleSearch with function declarations verified live
            # 25.08 (all three tool layouts PASS on gemini-live-2.5-flash).
            tools=[
                types.Tool(google_search=types.GoogleSearch()),
                *([types.Tool(function_declarations=[TAKE_PHOTO_DECL])]
                  if self.cfg.tool_executor else []),
            ],
            system_instruction=self.cfg.system_instruction or None,
            # transparent=True is what adk-python's production reconnect loop
            # sets on the Vertex backend (base_llm_flow.py) — the server carries
            # session state across reconnects; new_handle still arrives for
            # explicit resume after a full drop.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resumption_handle, transparent=True),
        )

    # -- session lifecycle ---------------------------------------------------
    async def start(self) -> None:
        self._runner_task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stopping = True
        if self._runner_task:
            self._runner_task.cancel()

    async def reset(self) -> None:
        """Fresh conversation: drop the resumption handle and reconnect.
        The Live session otherwise accumulates every past frame/exchange
        (live 25.08: it kept steering a new user toward an old test's sink)."""
        self._resumption_handle = None
        self._goaway = False
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._connected.clear()
        self._session = None
        self._stopping = False
        self._runner_task = asyncio.create_task(self._run_forever())

    async def _run_forever(self) -> None:
        backoff = self.cfg.reconnect_backoff_s
        while not self._stopping:
            try:
                async with self._client.aio.live.connect(
                        model=self.cfg.model, config=self._connect_config()) as session:
                    self._session = session
                    self._goaway = False
                    self._connected.set()
                    log.info("live session connected (resume=%s, take_photo_tool=%s)",
                             bool(self._resumption_handle),
                             self.cfg.tool_executor is not None)
                    backoff = self.cfg.reconnect_backoff_s
                    sender = asyncio.create_task(self._frame_trickle(session))
                    try:
                        while not self._goaway:
                            async for msg in session.receive():
                                self._handle_message(msg)
                                if self._goaway:
                                    break
                    finally:
                        sender.cancel()
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001 - any transport error → reconnect
                log.warning("live session dropped: %s: %s", type(e).__name__, e)
            self._connected.clear()
            self._session = None
            if self._pending is not None and not self._pending.done():
                self._pending.set_exception(ConnectionError("session dropped mid-turn"))
            if not self._stopping:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    async def _frame_trickle(self, session) -> None:
        """Background: keep the model's eyes fresh at a bounded rate."""
        while True:
            data = self.frame.take_fresh()
            if data is not None:
                try:
                    await session.send_realtime_input(
                        media=types.Blob(data=data, mime_type="image/jpeg"))
                except Exception as e:  # noqa: BLE001 - runner handles reconnect
                    log.warning("frame send failed: %s", e)
                    return
            await asyncio.sleep(self.cfg.frame_interval_s)

    # -- public API ----------------------------------------------------------
    def push_frame(self, data: bytes) -> None:
        self.frame.set(data)

    async def ask(self, text: str) -> str:
        """Send one user utterance (with the freshest frame) and await the reply."""
        async with self._turn_lock:
            await asyncio.wait_for(self._connected.wait(), self.cfg.ask_timeout_s)
            session = self._session
            if session is None:
                raise ConnectionError("no live session")
            loop = asyncio.get_running_loop()
            self._turn_buf = []
            self.tool_ran = None
            self._pending = loop.create_future()
            # The frame rides INSIDE the question's turn. A frame pushed via
            # send_realtime_input just before the text is not reliably attached
            # yet — verified 25.08: the model answered about a "washing machine"
            # / "outdoor AC unit" for a water-heater plate. In-turn = guaranteed.
            parts: list[types.Part] = []
            data = self.frame.take_fresh() or self.frame.peek()
            if data is not None:
                parts.append(types.Part(inline_data=types.Blob(data=data, mime_type="image/jpeg")))
                parts.append(types.Part(text=text))
            else:
                # No frame: say so IN the turn. The persona alone did not hold —
                # live 25.08 the model caved to social pressure ("Camera,
                # buddy") and invented a valve plus repair steps with no
                # image at all. A hard system marker beats a standing rule.
                age = self.frame.age_s
                state = ("you have received no photo at all" if age is None
                         else f"your last photo is {age:.0f}s old and stale")
                fresh_path = ("call your take_photo tool NOW and answer from the "
                              "photo that follows" if self.cfg.tool_executor
                              else "ask them to say 'take a photo'")
                parts.append(types.Part(
                    text=f"[SYSTEM: no photo is attached to this turn — {state}. "
                         f"Do NOT describe what you 'currently' see and never "
                         f"invent objects. If answering needs sight, {fresh_path}.]\n"
                         f"User: {text}"))
            await session.send_client_content(turns=types.Content(role="user", parts=parts))
            try:
                reply = await asyncio.wait_for(self._pending, self.cfg.ask_timeout_s)
            finally:
                self._pending = None
            # The model drove its own camera: the executor pushed the new frame
            # into self.frame, but a frame cannot ride a tool_response — attach
            # it in a follow-up turn so the answer is about the ACTUAL capture
            # (in-turn attach is the only reliable path, probe 25.08).
            if self.tool_ran == "take_photo" and self.frame.peek() is not None:
                self._turn_buf = []
                self._pending = loop.create_future()
                await session.send_client_content(turns=types.Content(role="user", parts=[
                    types.Part(inline_data=types.Blob(
                        data=self.frame.peek(), mime_type="image/jpeg")),
                    types.Part(text="[SYSTEM: this is the photo take_photo just captured. "
                                    "Answer the user's question from it.]"),
                ]))
                try:
                    follow = await asyncio.wait_for(self._pending, self.cfg.ask_timeout_s)
                finally:
                    self._pending = None
                return follow or reply
            return reply
