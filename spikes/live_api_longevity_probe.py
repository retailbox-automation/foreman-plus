"""Vertex Live API longevity probe: does a session with periodic JPEG frames
survive past the documented 2-min audio+video limit? Tests session_resumption
handle delivery + GoAway warnings.

Run: .venv/bin/python spikes/live_api_longevity_probe.py  (~6 min)
"""
import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
FRAME = (Path(__file__).parent / "assets" / "nameplate.jpg").read_bytes()
MODEL = "gemini-live-2.5-flash"
DURATION_S = 360
FRAME_EVERY_S = 2
ASK_EVERY_S = 45


async def main():
    client = genai.Client(vertexai=True, project=PROJECT, location="global")
    cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        session_resumption=types.SessionResumptionConfig(),
    )
    t0 = time.monotonic()
    resumption_handles = 0
    goaway = None
    frames_sent = 0
    answers = 0

    def ts() -> str:
        return f"{time.monotonic() - t0:6.1f}s"

    try:
        async with client.aio.live.connect(model=MODEL, config=cfg) as session:
            print(f"[{ts()}] connected")

            async def sender():
                nonlocal frames_sent
                last_ask = 0.0
                while time.monotonic() - t0 < DURATION_S:
                    await session.send_realtime_input(
                        media=types.Blob(data=FRAME, mime_type="image/jpeg"))
                    frames_sent += 1
                    if time.monotonic() - last_ask > ASK_EVERY_S:
                        last_ask = time.monotonic()
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(
                                text="In 5 words: what do you currently see?")]))
                    await asyncio.sleep(FRAME_EVERY_S)

            async def receiver():
                nonlocal resumption_handles, goaway, answers
                buf = ""
                # receive() generator ENDS at each turn boundary — must loop it,
                # or the socket stops being read (probe v1 died of exactly this:
                # answers=1, then 1011 keepalive timeout at 230s).
                while True:
                    async for msg in session.receive():
                        if msg.session_resumption_update and msg.session_resumption_update.resumable:
                            resumption_handles += 1
                        if msg.go_away:
                            goaway = f"[{ts()}] GoAway: time_left={msg.go_away.time_left}"
                            print(goaway, flush=True)
                        if msg.text:
                            buf += msg.text
                        if msg.server_content and msg.server_content.turn_complete:
                            answers += 1
                            print(f"[{ts()}] answer #{answers}: {buf.strip()[:80]}", flush=True)
                            buf = ""

            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            await send_task
            recv_task.cancel()
            print(f"[{ts()}] SURVIVED full {DURATION_S}s")
    except Exception as e:  # noqa: BLE001
        print(f"[{ts()}] DIED: {type(e).__name__}: {str(e)[:300]}")
    print(f"frames={frames_sent} answers={answers} "
          f"resumption_handles={resumption_handles} goaway={goaway}")


if __name__ == "__main__":
    asyncio.run(main())
