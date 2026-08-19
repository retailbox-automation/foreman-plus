"""Foreman+ hello-fleet: root agent + estimator sub-agent (spike scope)."""
from google.adk.agents import Agent

MODEL = "gemini-3.6-flash"

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

root_agent = Agent(
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
