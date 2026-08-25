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


async def speak_bridge(text: str, url: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        await http.post(url, json={"text": text})


async def speak_local(text: str) -> None:
    proc = await asyncio.create_subprocess_exec("say", text)
    await proc.wait()


def make_app(brain: LiveBrain, frame_dir: Path, speak) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await brain.start()
        poller = asyncio.create_task(frame_dir_poller(frame_dir, brain.push_frame))
        yield
        poller.cancel()
        await brain.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "frame_age_s": brain.frame.age_s}

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
