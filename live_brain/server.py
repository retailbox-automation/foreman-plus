"""HTTP wiring for the live brain.

POST /utterance {"text": ...} → ask Gemini Live (with freshest frame) → reply
text; optionally forwarded to a speak sink (glass-bridge POST /say, or macOS
`say` for glasses-free testing).

Run: .venv/bin/python -m live_brain.server
Env: GOOGLE_CLOUD_PROJECT (required), FRAME_DIR (default captures/frames),
     BRIDGE_SAY_URL (optional http://localhost:7010/say), SPEAK_LOCAL=1 (say),
     LIVE_BRAIN_PORT (default 7020).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .brain import BrainConfig, LiveBrain
from .persona import GUIDANCE_PERSONA
from .sources import frame_dir_poller

log = logging.getLogger("live_brain.server")


class Utterance(BaseModel):
    text: str


class Frame(BaseModel):
    """One JPEG, base64 — the glasses bridge pushes each captured photo here so
    photo-mode Q&A works with no video stream (Cloud Run has no LAN/RTMP)."""
    image_b64: str


class StreamReq(BaseModel):
    """A live HLS URL (Mentra managed stream) to pull frames from."""
    url: str


class StreamPuller:
    """ffmpeg subprocess: HLS → numbered JPEGs in frame_dir. Restarts on death
    (the glasses project's known gotcha: ffmpeg dies when the ingest muxer
    resets and never recovers on its own)."""

    def __init__(self, frame_dir: Path) -> None:
        self.frame_dir = frame_dir
        self.url: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    @staticmethod
    def ffmpeg_cmd(url: str, frame_dir: Path) -> list[str]:
        return [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1", "-reconnect_on_http_error", "4xx,5xx",
            "-reconnect_delay_max", "10", "-rw_timeout", "15000000",
            "-live_start_index", "-1",
            "-i", url,
            "-vf", "fps=1/2,scale=1280:-2", "-q:v", "4",
            str(frame_dir / "stream-%05d.jpg"),
        ]

    async def start(self, url: str) -> None:
        await self.stop()
        self._stopping = False
        self.url = url
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        if self._task:
            self._task.cancel()
            self._task = None
        self.url = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _newest_frame_age(self) -> float | None:
        mtimes = [p.stat().st_mtime for p in self.frame_dir.glob("stream-*.jpg")]
        return None if not mtimes else time.time() - max(mtimes)

    async def _run(self) -> None:
        restarts = 0
        while not self._stopping and self.url and restarts < 30:
            for old in self.frame_dir.glob("stream-*.jpg"):
                old.unlink(missing_ok=True)
            log.info("stream puller: starting ffmpeg for %s", self.url)
            self._proc = await asyncio.create_subprocess_exec(
                *self.ffmpeg_cmd(self.url, self.frame_dir))
            started = time.monotonic()
            # Staleness watchdog: ffmpeg is known to HANG (not exit) when the
            # ingest muxer resets (glasses project, 07-15 live test) — its own
            # reconnect flags don't cover that, so we kill on frozen output.
            while True:
                try:
                    rc: int | None = await asyncio.wait_for(
                        asyncio.shield(self._proc.wait()), timeout=4)
                    break
                except asyncio.TimeoutError:
                    age = self._newest_frame_age()
                    no_output_s = time.monotonic() - started
                    if (age is None and no_output_s > 40) or (age is not None and age > 12):
                        log.warning("stream frames stale (age=%s, up=%.0fs) — killing ffmpeg",
                                    f"{age:.1f}s" if age else "none", no_output_s)
                        self._proc.terminate()
                        rc = await self._proc.wait()
                        break
            if self._stopping:
                break
            restarts += 1
            log.warning("stream ffmpeg exited rc=%s, restart #%d in 2s", rc, restarts)
            await asyncio.sleep(min(2 * restarts, 15))


async def speak_bridge(text: str, url: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        await http.post(url, json={"text": text})


async def speak_local(text: str) -> None:
    proc = await asyncio.create_subprocess_exec("say", text)
    await proc.wait()


def make_app(brain: LiveBrain, frame_dir: Path, speak) -> FastAPI:
    puller = StreamPuller(frame_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await brain.start()
        poller = asyncio.create_task(frame_dir_poller(frame_dir, brain.push_frame))
        yield
        poller.cancel()
        await puller.stop()
        await brain.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "frame_age_s": brain.frame.age_s,
                "streaming": puller.running, "stream_url": puller.url}

    @app.post("/stream")
    async def stream_start(s: StreamReq) -> dict:
        if not s.url.startswith("http"):
            raise HTTPException(status_code=400, detail="url must be an HLS http(s) URL")
        await puller.start(s.url)
        return {"ok": True, "url": s.url}

    @app.delete("/stream")
    async def stream_stop() -> dict:
        await puller.stop()
        return {"ok": True}

    @app.post("/frame")
    async def frame(f: Frame) -> dict:
        try:
            data = base64.b64decode(f.image_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="image_b64 is not valid base64")
        if not data:
            raise HTTPException(status_code=400, detail="empty frame")
        brain.push_frame(data)
        return {"ok": True, "bytes": len(data)}

    @app.post("/utterance")
    async def utterance(u: Utterance) -> dict:
        try:
            reply = await brain.ask(u.text)
        except (ConnectionError, asyncio.TimeoutError) as e:
            reply = "Sorry, I lost the link for a second. Say that again."
            log.warning("ask failed: %s", e)
        if speak is not None and reply:
            try:
                await speak(reply)
            except Exception as e:  # noqa: BLE001 - reply still returned to caller
                log.warning("speak sink failed: %s", e)
        return {"reply": reply}

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    frame_dir = Path(os.environ.get("FRAME_DIR", "captures/frames"))
    frame_dir.mkdir(parents=True, exist_ok=True)
    cfg = BrainConfig(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        system_instruction=GUIDANCE_PERSONA,
    )
    say_url = os.environ.get("BRIDGE_SAY_URL")
    speak = None
    if say_url:
        async def speak_via_bridge(text: str) -> None:
            await speak_bridge(text, say_url)
        speak = speak_via_bridge
    elif os.environ.get("SPEAK_LOCAL") == "1":
        speak = speak_local
    app = make_app(LiveBrain(cfg), frame_dir, speak)
    # Cloud Run injects PORT and needs 0.0.0.0; local default stays loopback.
    port = int(os.environ.get("PORT") or os.environ.get("LIVE_BRAIN_PORT", "7020"))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
