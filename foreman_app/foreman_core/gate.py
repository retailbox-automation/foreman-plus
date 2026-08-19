"""Write-gate: every memory write is proposed, verified, journaled — then applied.

Integrity properties (each backed by a test):
- identity check before any LLM call; unregistered agents never reach the verifier
- size + predicate caps rejected BEFORE the verifier (no billed call for garbage)
- check-and-act serialized per (subject, predicate) via a pg advisory lock, so the
  verifier always judges against the state that holds when the write lands
- journal close + fact write are one transaction (store.apply_approved)
- verifier failure fails CLOSED; raw exception text stays in the journal only
"""
import json
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
    def __init__(
        self,
        store: MemoryStore,
        verifier: Verifier,
        max_value_bytes: int = 4096,
        max_predicates_per_subject: int = 64,
    ):
        self.store = store
        self.verifier = verifier
        self.max_value_bytes = max_value_bytes
        self.max_predicates_per_subject = max_predicates_per_subject

    async def submit(self, proposal: Proposal) -> GateEntry:
        entry_id = await self._journal_open(proposal)

        # identity check first — unregistered agents never reach the LLM verifier
        if not await self.store.agent_exists(proposal.proposed_by):
            reason = f"agent '{proposal.proposed_by}' is not registered"
            await self._journal_close(entry_id, "rejected", reason, None)
            return GateEntry(entry_id, "rejected", reason)

        # cheap guards before any billed LLM call
        size = len(json.dumps(proposal.object))
        if size > self.max_value_bytes:
            reason = f"value size {size}B exceeds cap {self.max_value_bytes}B"
            await self._journal_close(entry_id, "rejected", reason, None)
            return GateEntry(entry_id, "rejected", reason)

        if await self.store.predicate_count(proposal.subject) >= self.max_predicates_per_subject:
            reason = (f"subject has reached the predicate cap "
                      f"({self.max_predicates_per_subject}); new predicates rejected")
            await self._journal_close(entry_id, "rejected", reason, None)
            return GateEntry(entry_id, "rejected", reason)

        # serialize check-and-act per (subject, predicate): the advisory lock is
        # held across read -> verify (LLM) -> write. The WHOLE critical section
        # runs on this ONE connection — a second pool acquire here would starve
        # the pool under concurrent submits (N lock-waiters each holding a conn).
        lock_key = f"{proposal.subject}|{proposal.predicate}"
        async with self.store.pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtext($1))", lock_key)
            try:
                return await self._verify_and_apply(proposal, entry_id, conn)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", lock_key)

    async def _verify_and_apply(self, proposal: Proposal, entry_id: int, conn) -> GateEntry:
        existing = [
            f for f in await self.store.current_facts(proposal.subject, conn=conn)
            if f["predicate"] == proposal.predicate
        ]
        try:
            verdict = await self.verifier.verify(proposal, existing)
        except Exception as e:  # fail closed: a broken verifier must not admit writes
            detail = f"verifier error: {str(e)[:500]}"
            await self._journal_close(entry_id, "rejected", detail, None, conn=conn)
            # agents/users get a generic reason; the journal keeps the detail
            return GateEntry(entry_id, "rejected", "verifier error: temporarily unavailable")

        if not verdict.approved:
            await self._journal_close(entry_id, "rejected", verdict.reason, verdict.model,
                                      conn=conn)
            return GateEntry(entry_id, "rejected", verdict.reason)

        fact_id = await self.store.apply_approved(
            proposal.subject, proposal.predicate, proposal.object,
            proposal.proposed_by, entry_id, verdict.reason, verdict.model, conn=conn,
        )
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
        self, entry_id: int, verdict: str, reason: str, model: str | None, conn=None
    ) -> None:
        sql = """UPDATE gate_journal
                 SET verdict = $2, reason = $3, verifier_model = $4, decided_at = now()
                 WHERE id = $1"""
        if conn is not None:
            await conn.execute(sql, entry_id, verdict, reason, model)
        else:
            async with self.store.pool.acquire() as c:
                await c.execute(sql, entry_id, verdict, reason, model)
