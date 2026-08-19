"""Write-gate: every memory write is proposed, verified, journaled — then applied."""
from dataclasses import dataclass
from typing import Any, Protocol

from .memory import MemoryStore


@dataclass
class Proposal:
    subject: str
    predicate: str
    object: dict[str, Any]
    proposed_by: str
    session_id: str | None = None


@dataclass
class Verdict:
    approved: bool
    reason: str
    model: str | None = None


@dataclass
class GateEntry:
    id: int
    verdict: str
    reason: str
    fact_id: int | None = None


class Verifier(Protocol):
    async def verify(self, proposal: Proposal, existing_facts: list[dict]) -> Verdict: ...


class WriteGate:
    def __init__(self, store: MemoryStore, verifier: Verifier):
        self.store = store
        self.verifier = verifier

    async def submit(self, proposal: Proposal) -> GateEntry:
        entry_id = await self._journal_open(proposal)

        # identity check first — unregistered agents never reach the LLM verifier
        if not await self.store.agent_exists(proposal.proposed_by):
            reason = f"agent '{proposal.proposed_by}' is not registered"
            await self._journal_close(entry_id, "rejected", reason, None)
            return GateEntry(entry_id, "rejected", reason)

        existing = [
            f for f in await self.store.current_facts(proposal.subject)
            if f["predicate"] == proposal.predicate
        ]
        try:
            verdict = await self.verifier.verify(proposal, existing)
        except Exception as e:  # fail closed: a broken verifier must not admit writes
            reason = f"verifier error: {e}"
            await self._journal_close(entry_id, "rejected", reason, None)
            return GateEntry(entry_id, "rejected", reason)

        if not verdict.approved:
            await self._journal_close(entry_id, "rejected", verdict.reason, verdict.model)
            return GateEntry(entry_id, "rejected", verdict.reason)

        fact_id = await self.store.insert_fact(
            proposal.subject, proposal.predicate, proposal.object,
            proposal.proposed_by, entry_id,
        )
        await self._journal_close(entry_id, "approved", verdict.reason, verdict.model)
        return GateEntry(entry_id, "approved", verdict.reason, fact_id)

    async def _journal_open(self, p: Proposal) -> int:
        async with self.store.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO gate_journal (proposed_by, session_id, proposal)
                   VALUES ($1, $2, $3) RETURNING id""",
                p.proposed_by, p.session_id,
                {"subject": p.subject, "predicate": p.predicate, "object": p.object},
            )

    async def _journal_close(
        self, entry_id: int, verdict: str, reason: str, model: str | None
    ) -> None:
        async with self.store.pool.acquire() as conn:
            await conn.execute(
                """UPDATE gate_journal
                   SET verdict = $2, reason = $3, verifier_model = $4, decided_at = now()
                   WHERE id = $1""",
                entry_id, verdict, reason, model,
            )
