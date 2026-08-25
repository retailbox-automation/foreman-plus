"""Does the model actually SEE a frame sent via send_realtime_input right
before the question, vs. a frame carried inside the question's own turn?
Ground truth: spikes/assets/nameplate.jpg is a Rheem water heater data plate.

Run: .venv/bin/python spikes/live_api_frame_attach_probe.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
FRAME = (Path(__file__).parent / "assets" / "nameplate.jpg").read_bytes()
Q = "One sentence: what appliance is this data plate from, and which brand?"


async def turn(session) -> str:
    buf = ""
    async for msg in session.receive():
        if msg.text:
            buf += msg.text
        if msg.server_content and msg.server_content.turn_complete:
            break
    return buf.strip()


async def main():
    client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location="global")
    cfg = types.LiveConnectConfig(response_modalities=[types.Modality.TEXT])
    for trial in range(3):
        async with client.aio.live.connect(model="gemini-live-2.5-flash", config=cfg) as s:
            await s.send_realtime_input(media=types.Blob(data=FRAME, mime_type="image/jpeg"))
            await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=Q)]))
            print(f"[realtime-then-text #{trial}] {await turn(s)}")
        async with client.aio.live.connect(model="gemini-live-2.5-flash", config=cfg) as s:
            await s.send_client_content(turns=types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(data=FRAME, mime_type="image/jpeg")),
                types.Part(text=Q)]))
            print(f"[in-turn #{trial}]            {await turn(s)}")


if __name__ == "__main__":
    asyncio.run(main())
