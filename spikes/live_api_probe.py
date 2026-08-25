"""Vertex Live API probe: which model ids / locations accept a Live WS session,
does TEXT response modality work, can we send a JPEG frame mid-session, latency.

Run: .venv/bin/python spikes/live_api_probe.py
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

LOCATIONS = ["us-central1", "global"]
MODELS = [
    "gemini-live-2.5-flash",
    "gemini-live-2.5-flash-native-audio",
    "gemini-live-2.5-flash-preview-native-audio",
    "gemini-2.0-flash-live-preview-04-09",
]


async def probe(location: str, model: str) -> dict:
    client = genai.Client(vertexai=True, project=PROJECT, location=location)
    cfg = types.LiveConnectConfig(response_modalities=["TEXT"])
    t0 = time.monotonic()
    try:
        async with client.aio.live.connect(model=model, config=cfg) as session:
            t_conn = time.monotonic() - t0
            # turn 1: plain text
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="Reply with exactly: OK")])
            )
            t1 = time.monotonic()
            reply1 = ""
            async for msg in session.receive():
                if msg.text:
                    reply1 += msg.text
                if msg.server_content and msg.server_content.turn_complete:
                    break
            t_text = time.monotonic() - t1
            # turn 2: image frame via realtime input + question
            await session.send_realtime_input(
                media=types.Blob(data=FRAME, mime_type="image/jpeg")
            )
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(
                    text="One short sentence: what appliance data plate is this and what model number do you see?")])
            )
            t2 = time.monotonic()
            reply2 = ""
            async for msg in session.receive():
                if msg.text:
                    reply2 += msg.text
                if msg.server_content and msg.server_content.turn_complete:
                    break
            t_frame = time.monotonic() - t2
            return {
                "ok": True, "connect_s": round(t_conn, 2),
                "text_turn_s": round(t_text, 2), "frame_turn_s": round(t_frame, 2),
                "reply1": reply1.strip()[:60], "reply2": reply2.strip()[:160],
            }
    except Exception as e:  # noqa: BLE001 - probe reports every failure mode
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def main():
    for loc in LOCATIONS:
        for model in MODELS:
            res = await probe(loc, model)
            status = "PASS" if res.pop("ok") else "FAIL"
            print(f"[{status}] {loc} / {model}: {res}")


if __name__ == "__main__":
    asyncio.run(main())
