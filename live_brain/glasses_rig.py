"""Rig glue for the Mentra glass-bridge (old project) — ZERO changes to it.

The old bridge already: transcribes speech into captures/transcripts/
YYYY-MM-DD-live.md, starts a local RTMP stream whose ffmpeg writes JPEG frames,
and speaks via POST :7010/say (ru-safe TTS pinned there). This rig tails the
transcript, forwards utterances to LiveBrain (Gemini Live on Vertex), and
speaks replies back — replacing the old Claude Code brain.

Run: .venv/bin/python -m live_brain.glasses_rig
Env: GLASSES_PROJ (default ~/Projects/Retailbox - Mentra Glasses),
     BRIDGE_SAY_URL (default http://localhost:7010/say),
     GOOGLE_CLOUD_PROJECT (required).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .brain import BrainConfig, LiveBrain
from .persona import GUIDANCE_PERSONA
from .sources import frame_dir_poller

log = logging.getLogger("live_brain.rig")

SPEECH_RE = re.compile(r"^- \[\d\d:\d\d:\d\d\](?: \(([a-z-]{2,7})\))? (.+)$")
ECHO_MARK = "(echo?)"
EVENT_MARKS = ("🔘", "📸", "🎥", "👆", "📷")
FRAMES_RE = re.compile(r"frames → (.+)$")
MUTE_RE = re.compile(r"\b(хватит|помолчи|тишина|quiet|stop talking)\b", re.I)
UNMUTE_RE = re.compile(r"\b(ассистент|форман|foreman|assistant)\b", re.I)


def parse_line(line: str):
    """→ ('utterance', text) | ('frames_dir', path) | None (event/echo/marker)."""
    line = line.rstrip()
    m = FRAMES_RE.search(line)
    if m and "LIVE" in line:
        return ("frames_dir", m.group(1).strip())
    if not line.startswith("- ["):
        return None
    if ECHO_MARK in line:
        return None
    if any(mark in line for mark in EVENT_MARKS):
        return None
    m = SPEECH_RE.match(line)
    if not m:
        return None
    text = m.group(2).strip()
    return ("utterance", text) if text else None


class MuteGate:
    """Respond by default; 'хватит/quiet' mutes, 'ассистент/foreman' unmutes."""

    def __init__(self) -> None:
        self.muted = False

    def admit(self, text: str) -> bool:
        if MUTE_RE.search(text):
            self.muted = True
            return False
        if self.muted and UNMUTE_RE.search(text):
            self.muted = False
            return True
        return not self.muted


async def tail_transcript(transcript_dir: Path, on_parsed, poll_s: float = 0.4) -> None:
    """Byte-offset tail of today's transcript file (handles day rollover)."""
    offsets: dict[Path, int] = {}
    while True:
        file = transcript_dir / f"{dt.date.today().isoformat()}-live.md"
        if file.exists():
            size = file.stat().st_size
            base = offsets.get(file)
            if base is None:
                offsets[file] = size  # start at EOF: only NEW speech, no replay
            elif size > base:
                with file.open("r", encoding="utf-8") as fh:
                    fh.seek(base)
                    chunk = fh.read()
                offsets[file] = base + len(chunk.encode("utf-8"))
                for line in chunk.splitlines():
                    parsed = parse_line(line)
                    if parsed:
                        await on_parsed(*parsed)
        await asyncio.sleep(poll_s)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    proj = Path(os.environ.get(
        "GLASSES_PROJ", str(Path.home() / "Projects" / "Retailbox - Mentra Glasses")))
    say_url = os.environ.get("BRIDGE_SAY_URL", "http://localhost:7010/say")
    brain = LiveBrain(BrainConfig(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        system_instruction=GUIDANCE_PERSONA))
    await brain.start()
    gate = MuteGate()
    poller_task: asyncio.Task | None = None
    http = httpx.AsyncClient(timeout=20)

    async def speak(text: str) -> None:
        r = await http.post(say_url, json={"text": text})
        if r.status_code != 200:
            log.warning("/say -> %s %s", r.status_code, r.text[:120])

    async def on_parsed(kind: str, value: str) -> None:
        nonlocal poller_task
        if kind == "frames_dir":
            if poller_task:
                poller_task.cancel()
            log.info("frames dir -> %s", value)
            poller_task = asyncio.create_task(
                frame_dir_poller(Path(value), brain.push_frame))
            return
        if not gate.admit(value):
            log.info("muted, skipping: %s", value[:60])
            return
        log.info("USER: %s", value)
        try:
            reply = await brain.ask(value)
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            log.warning("ask failed: %s", e)
            return
        log.info("BRAIN: %s", reply)
        if reply:
            await speak(reply)

    # pick up an already-running stream's frames dir via .live-see.current
    marker = proj / "captures" / ".live-see.current"
    if marker.exists():
        current = marker.read_text().strip()
        if current and Path(current).is_dir():
            await on_parsed("frames_dir", current)

    log.info("tailing %s", proj / "captures" / "transcripts")
    await tail_transcript(proj / "captures" / "transcripts", on_parsed)


if __name__ == "__main__":
    asyncio.run(main())
