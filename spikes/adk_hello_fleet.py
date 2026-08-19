"""Spike 2 (19.08): does our fleet+shared-memory pattern fit ADK?

Proves 4 assumptions in one run:
  1. ADK LlmAgent fleet (root -> sub-agent) runs on gemini-3.6-flash via API key.
  2. DatabaseSessionService persists sessions/events to Postgres (our memory layer).
  3. Root agent delegates to sub-agent (A2A-style transfer inside ADK).
  4. Session survives process restart: second Runner re-reads state from DB.

Run: .venv/bin/python spikes/adk_hello_fleet.py
"""
import asyncio
import os
import sys
from pathlib import Path

# env: GEMINI_API_KEY -> GOOGLE_API_KEY (ADK/google-genai reads the latter)
env_file = Path(__file__).resolve().parent.parent / ".env"
for line in env_file.read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

DB_URL = "postgresql+asyncpg://oskolamicheal@localhost:5432/foreman_spike"
MODEL = "gemini-3.6-flash"
APP = "foreman_spike"
USER = "mikhail"
SESSION_ID = "spike-session-1"

estimator = Agent(
    name="estimator",
    model=MODEL,
    description="Estimates repair scope and cost for home equipment problems.",
    instruction=(
        "You are the estimator agent of a repair fleet. Given an equipment "
        "problem, reply with a one-line JSON estimate: "
        '{"job": str, "hours": int, "parts": [str]}. Nothing else.'
    ),
)

foreman = Agent(
    name="foreman",
    model=MODEL,
    description="Foreman: routes incoming repair requests to specialist agents.",
    instruction=(
        "You are the foreman of a repair fleet. For any equipment problem the "
        "user describes, transfer to the estimator agent to get the estimate, "
        "then present its JSON verbatim to the user."
    ),
    sub_agents=[estimator],
)


async def run_turn(runner: Runner, text: str) -> str:
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    final = ""
    async for event in runner.run_async(user_id=USER, session_id=SESSION_ID, new_message=msg):
        author = getattr(event, "author", "?")
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    print(f"  [{author}] {p.text.strip()[:200]}")
                if getattr(p, "function_call", None):
                    print(f"  [{author}] -> call {p.function_call.name}")
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return final


async def main() -> None:
    svc = DatabaseSessionService(db_url=DB_URL)
    await svc.create_session(app_name=APP, user_id=USER, session_id=SESSION_ID)
    runner = Runner(agent=foreman, app_name=APP, session_service=svc)

    print("=== turn 1: photo-style problem report ===")
    await run_turn(
        runner,
        "Water heater Rheem 82V40-2 from 2004 is leaking from the bottom. What's the scope?",
    )

    # assumption 4: a FRESH service+runner (new process semantics) sees the session
    svc2 = DatabaseSessionService(db_url=DB_URL)
    sess = await svc2.get_session(app_name=APP, user_id=USER, session_id=SESSION_ID)
    n_events = len(sess.events) if sess else -1
    print(f"\n=== re-read from Postgres: session found={sess is not None}, events={n_events} ===")

    runner2 = Runner(agent=foreman, app_name=APP, session_service=svc2)
    print("\n=== turn 2 (fresh runner, memory from DB): follow-up ===")
    final = await run_turn(runner2, "Remind me: which model did I report and how old is it?")

    ok = sess is not None and n_events >= 2 and ("82V40" in final or "2004" in final)
    print(f"\nSPIKE {'PASSED' if ok else 'FAILED'}: persistence+recall={'OK' if ok else 'BROKEN'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
