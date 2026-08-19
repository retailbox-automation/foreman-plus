"""Agent-facing memory tools. Every write goes through the gate; nothing raises."""
from typing import Any

from .gate import Proposal, WriteGate
from .memory import MemoryStore


def make_recall_tool(store: MemoryStore, embedder):
    """Semantic recall across the WHOLE fleet memory (current facts only)."""

    async def memory_recall(query: str) -> dict:
        """Semantically search shared fleet memory across all jobs. Returns the
        most similar current facts with their subjects and similarity scores."""
        try:
            qvec = await embedder.embed(query, kind="query")
            hits = await store.recall(qvec, top_k=5)
            return {"hits": [
                {"subject": h["subject"], "predicate": h["predicate"],
                 "value": h["object"].get("value"), "score": round(h["score"], 3)}
                for h in hits
            ]}
        except Exception as e:
            return {"hits": [], "error": str(e)}

    return memory_recall


def make_memory_tools(agent_name: str, store: MemoryStore, gate: WriteGate):
    """Returns (memory_write, memory_search) bound to one agent's identity."""

    async def memory_write(subject: str, predicate: str, value: Any) -> dict:
        """Propose writing one fact to shared memory. The write-gate verifies it
        against existing facts; the outcome (approved/rejected + reason) is returned."""
        try:
            entry = await gate.submit(
                Proposal(
                    subject=subject,
                    predicate=predicate,
                    object={"value": value},
                    proposed_by=agent_name,
                )
            )
            return {"verdict": entry.verdict, "reason": entry.reason,
                    "gate_entry_id": entry.id}
        except Exception as e:
            return {"verdict": "error", "reason": str(e)}

    async def memory_search(subject: str) -> dict:
        """Read the current facts about a subject from shared memory."""
        try:
            facts = await store.current_facts(subject)
            return {"facts": [
                {"predicate": f["predicate"], "value": f["object"].get("value"),
                 "source_agent": f["source_agent"]}
                for f in facts
            ]}
        except Exception as e:
            return {"facts": [], "error": str(e)}

    return memory_write, memory_search
