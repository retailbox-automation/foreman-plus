"""Foreman+ fleet: root agent + estimator, with gated shared memory."""
from google.adk.agents import Agent

from . import runtime
from .foreman_core.tools import make_memory_tools

MODEL = "gemini-3.7-flash"


def _tools_for(agent_name: str):
    async def record_fact(subject: str, predicate: str, value: str) -> dict:
        """Record one fact into shared fleet memory. The write-gate verifies it
        against existing facts; returns the verdict (approved/rejected + reason)."""
        store, gate = await runtime.get_env()
        write, _ = make_memory_tools(agent_name, store, gate)
        return await write(subject=subject, predicate=predicate, value=value)

    async def lookup_facts(subject: str) -> dict:
        """Read all current facts about a subject from shared fleet memory."""
        store, gate = await runtime.get_env()
        _, search = make_memory_tools(agent_name, store, gate)
        return await search(subject=subject)

    return [record_fact, lookup_facts]


estimator = Agent(
    name="estimator",
    model=MODEL,
    description="Estimates repair scope and cost for home equipment problems.",
    instruction=(
        "You are the estimator agent of a repair fleet. When asked about a job "
        '"Job <ID>", FIRST call lookup_facts with subject "job:<ID>" to read what '
        "is known. Then reply with a one-line JSON estimate: "
        '{"job": str, "hours": int, "parts": [str]} and record it via record_fact '
        '(subject "job:<ID>", predicate "estimate", value = that JSON as a string).'
    ),
    tools=_tools_for("estimator"),
)

root_agent = Agent(
    name="foreman",
    model=MODEL,
    description="Foreman: intake of repair requests, routing to specialist agents.",
    instruction=(
        'You are the foreman of a repair fleet. When a user reports a problem "Job '
        '<ID>: ...", FIRST record every concrete reported attribute into shared '
        'memory via record_fact with subject "job:<ID>" — use predicates like '
        "equipment_model, serial_number, manufacture_date, issue. Then transfer to "
        "the estimator agent for the scope. Present its JSON verbatim to the user. "
        "If a record_fact call returns verdict rejected, tell the user which fact "
        "was rejected and why instead of silently dropping it."
    ),
    sub_agents=[estimator],
    tools=_tools_for("foreman"),
)
