"""Frame sources: directory of JPEGs (ffmpeg output) and a webcam helper."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger("live_brain.sources")


def latest_jpeg(frame_dir: Path) -> tuple[bytes, float] | None:
    """Newest .jpg in dir as (bytes, mtime); None if dir empty/missing."""
    try:
        files = [p for p in frame_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")]
    except FileNotFoundError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        return newest.read_bytes(), newest.stat().st_mtime
    except OSError:
        return None


async def frame_dir_poller(frame_dir: Path, push, poll_s: float = 0.5) -> None:
    """Push newest frame into `push(bytes)` whenever a newer file appears."""
    last_mtime = 0.0
    while True:
        found = latest_jpeg(frame_dir)
        if found is not None:
            data, mtime = found
            if mtime > last_mtime:
                last_mtime = mtime
                push(data)
        await asyncio.sleep(poll_s)


def webcam_ffmpeg_cmd(frame_dir: Path, fps: float = 0.5, device: str = "0") -> str:
    """macOS webcam → JPEG frames, for glasses-free dogfood of the full loop."""
    return (
        f'ffmpeg -f avfoundation -framerate 30 -i "{device}" '
        f'-vf fps={fps} -qscale:v 4 -update 0 "{frame_dir}/frame_%05d.jpg"'
    )
