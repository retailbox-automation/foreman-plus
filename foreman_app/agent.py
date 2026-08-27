"""Foreman+ fleet: root agent + estimator + closer, with gated shared memory."""
from google.adk.agents import Agent

from . import runtime
from .foreman_core.tools import (
    make_closeout_tool,
    make_memory_tools,
    make_recall_tool,
)

MODEL = "gemini-3.7-flash"


def _tools_for(agent_name: str):
    async def record_fact(subject: str, predicate: str, value: str, source: str = "") -> dict:
        """Record one fact into shared fleet memory. `source` = where the value
        came from: "nameplate photo" | "technician voice" | "homeowner statement"
        | "plate unreadable" (for value "UNKNOWN"). The write-gate verifies it
        against existing facts; returns the verdict (approved/rejected + reason)."""
        store, gate = await runtime.get_env()
        write, _ = make_memory_tools(agent_name, store, gate)
        return await write(subject=subject, predicate=predicate, value=value, source=source)

    async def lookup_facts(subject: str) -> dict:
        """Read all current facts about a subject from shared fleet memory."""
        store, gate = await runtime.get_env()
        _, search = make_memory_tools(agent_name, store, gate)
        return await search(subject=subject)

    async def recall_similar(query: str) -> dict:
        """Semantically search the WHOLE fleet memory across all past jobs —
        similar equipment, similar issues, past estimates."""
        store, _ = await runtime.get_env()
        recall = make_recall_tool(store, runtime.get_embedder())
        return await recall(query=query)

    return [record_fact, lookup_facts, recall_similar]


async def close_out_job(job_id: str) -> dict:
    """Close out a job into its client-facing document, built strictly from
    gate-approved facts (honest unknowns, advisory warranty, refrigerant
    flags). Returns the document URL and a compact summary."""
    store, _ = await runtime.get_env()
    tool = make_closeout_tool(store)
    return await tool(job_id=job_id)


estimator = Agent(
    name="estimator",
    model=MODEL,
    description="Estimates repair scope and cost for home equipment problems.",
    instruction=(
        "You are the estimator agent of a repair fleet. When asked about a job "
        '"Job <ID>", FIRST call lookup_facts with subject "job:<ID>" to read what '
        "is known, and call recall_similar with a short description of the issue "
        "to check whether the fleet has seen similar equipment or problems on "
        "past jobs — use consistent past estimates as a sanity anchor. Then reply "
        'with a one-line JSON estimate: {"job": str, "hours": int, "parts": [str]} '
        'and record it via record_fact (subject "job:<ID>", predicate "estimate", '
        'value = that JSON as a string, source "estimator").'
    ),
    tools=_tools_for("estimator"),
)

closer = Agent(
    name="closer",
    model=MODEL,
    description="Closes a job into a verified client-facing document; briefs "
                "the next person from fleet memory.",
    instruction=(
        'You are the closer agent of a repair fleet. Two duties:\n'
        '1) When asked to close out "Job <ID>": call close_out_job with that '
        "job_id. Report the document_url, the verified facts, and — honestly — "
        "every unknown. If rejected_count > 0, say that rejected claims were "
        "kept OUT of the document by the write-gate. Mention any flags (A2L "
        "refrigerant, replacement conversation) in plain language. Never invent "
        "a value for an unknown field.\n"
        '2) When asked to brief the next person (comfort advisor, a different '
        "technician on a callback): call lookup_facts on the job and "
        "recall_similar on the issue, then give a short briefing: what is "
        "verified about the equipment, what was rejected and why, what past "
        "jobs the fleet remembers, and what remains unknown."
    ),
    tools=[close_out_job] + _tools_for("closer")[1:],  # lookup_facts, recall_similar
)

root_agent = Agent(
    name="foreman",
    model=MODEL,
    description="Foreman: intake of repair requests, routing to specialist agents.",
    instruction=(
        "You are the foreman of a repair fleet. Every intake names a job \"Job <ID>\" "
        "(or \"job <ID>\"). FIRST record facts into shared memory via record_fact with "
        "subject \"job:<ID>\", one call per fact, ALWAYS with a source tag:\n"
        "- property: the service address exactly as written in the intake text "
        "(source \"intake\"); technician: the technician's name (source \"intake\"); "
        "client: the client/homeowner name if given (source \"intake\").\n"
        "- What you READ on the nameplate photo: equipment_type, equipment_brand, "
        "equipment_model, serial_number, manufacture_date, capacity, refrigerant "
        "(source \"nameplate photo\"). If a plate field is present but unreadable, "
        "record value \"UNKNOWN\" with source \"plate unreadable\" — never guess.\n"
        "- What you HEAR or read in the technician's notes: issue, access_location, "
        "observations (source \"technician voice\"). Anything the technician attributes "
        "to the homeowner gets source \"homeowner statement\" and the homeowner's claim "
        "as the value.\n"
        "- Things noticed but not repaired: predicates deferred_1, deferred_2, ... "
        "(source \"technician voice\").\n"
        "Then transfer to the estimator agent for the scope and present its JSON "
        "verbatim. If a record_fact call returns verdict rejected, tell the user which "
        "fact was rejected and why instead of silently dropping it. When the user asks "
        "to close out a job or brief the next person, transfer to the closer agent."
    ),
    sub_agents=[estimator, closer],
    tools=_tools_for("foreman"),
)
