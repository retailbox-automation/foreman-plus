"""Bi-temporal shared memory over Postgres (asyncpg)."""
import datetime as dt
from typing import Any

import asyncpg


def _vec_text(v: list[float]) -> str:
    """pgvector text literal — avoids a codec dependency (cast with ::vector)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


class MemoryStore:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def register_agent(self, name: str, version: str, description: str = "") -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agents (name, version, description) VALUES ($1, $2, $3)
                   ON CONFLICT (name) DO UPDATE SET version = $2, description = $3""",
                name, version, description,
            )

    async def agent_exists(self, name: str) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM agents WHERE name = $1", name) > 0

    async def current_facts(
        self, subject: str, as_of: dt.datetime | None = None, limit: int = 200,
        conn=None,
    ) -> list[dict[str, Any]]:
        async def _q(c):
            if as_of is None:
                return await c.fetch(
                    "SELECT * FROM memory_facts WHERE subject = $1 AND valid_to IS NULL"
                    " ORDER BY id LIMIT $2", subject, limit,
                )
            return await c.fetch(
                """SELECT * FROM memory_facts
                   WHERE subject = $1 AND valid_from <= $2
                     AND (valid_to IS NULL OR valid_to > $2)
                   ORDER BY id LIMIT $3""",
                subject, as_of, limit,
            )
        if conn is not None:
            rows = await _q(conn)
        else:
            async with self.pool.acquire() as c:
                rows = await _q(c)
        return [dict(r) for r in rows]

    async def predicate_count(self, subject: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(DISTINCT predicate) FROM memory_facts"
                " WHERE subject = $1 AND valid_to IS NULL", subject,
            )

    async def fact_history(
        self, subject: str, predicate: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM memory_facts WHERE subject = $1 AND predicate = $2"
                " ORDER BY id LIMIT $3",
                subject, predicate, limit,
            )
        return [dict(r) for r in rows]

    async def gate_journal(
        self, subject: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            if subject is None:
                rows = await conn.fetch(
                    "SELECT * FROM gate_journal ORDER BY id LIMIT $1", limit)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM gate_journal WHERE proposal ->> 'subject' = $1"
                    " ORDER BY id LIMIT $2",
                    subject, limit,
                )
        return [dict(r) for r in rows]

    async def recall(
        self, query_embedding: list[float], top_k: int = 5,
        subject_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        """Nearest current facts by cosine similarity (superseded rows excluded)."""
        qvec = _vec_text(query_embedding)
        async with self.pool.acquire() as conn:
            if subject_prefix is None:
                rows = await conn.fetch(
                    """SELECT subject, predicate, object, source_agent,
                              1 - (embedding <=> $1::vector) AS score
                       FROM memory_facts
                       WHERE valid_to IS NULL AND embedding IS NOT NULL
                       ORDER BY embedding <=> $1::vector LIMIT $2""",
                    qvec, top_k,
                )
            else:
                rows = await conn.fetch(
                    """SELECT subject, predicate, object, source_agent,
                              1 - (embedding <=> $1::vector) AS score
                       FROM memory_facts
                       WHERE valid_to IS NULL AND embedding IS NOT NULL
                         AND subject LIKE $3
                       ORDER BY embedding <=> $1::vector LIMIT $2""",
                    qvec, top_k, subject_prefix + "%",
                )
        return [dict(r) for r in rows]

    async def apply_approved(
        self, subject: str, predicate: str, obj: dict, source_agent: str,
        entry_id: int, reason: str, model: str | None,
        embedding: list[float] | None = None, conn=None,
    ) -> int:
        """Close the journal entry AND write the fact in ONE transaction.

        Supersedes the current fact for (subject, predicate). Raises ValueError
        if the journal entry is missing or already decided — nothing is written.
        """
        if conn is not None:
            return await self._apply_approved_on(
                conn, subject, predicate, obj, source_agent, entry_id, reason,
                model, embedding)
        async with self.pool.acquire() as c:
            return await self._apply_approved_on(
                c, subject, predicate, obj, source_agent, entry_id, reason,
                model, embedding)

    async def _apply_approved_on(
        self, conn, subject: str, predicate: str, obj: dict,
        source_agent: str, entry_id: int, reason: str, model: str | None,
        embedding: list[float] | None = None,
    ) -> int:
        async with conn.transaction():
            closed = await conn.fetchval(
                """UPDATE gate_journal
                   SET verdict = 'approved', reason = $2, verifier_model = $3,
                       decided_at = now()
                   WHERE id = $1 AND verdict = 'pending' RETURNING id""",
                entry_id, reason, model,
            )
            if closed is None:
                raise ValueError(f"journal entry {entry_id} missing or not pending")
            prev_id = await conn.fetchval(
                """SELECT id FROM memory_facts
                   WHERE subject = $1 AND predicate = $2 AND valid_to IS NULL
                   FOR UPDATE""",
                subject, predicate,
            )
            # close the old row BEFORE inserting: the partial unique index
            # (one current row per subject+predicate) forbids two live rows
            # even transiently within the transaction
            if prev_id is not None:
                await conn.execute(
                    "UPDATE memory_facts SET valid_to = clock_timestamp() WHERE id = $1",
                    prev_id,
                )
            new_id = await conn.fetchval(
                """INSERT INTO memory_facts
                     (subject, predicate, object, source_agent, gate_entry_id,
                      valid_from, ingested_at, embedding)
                   VALUES ($1, $2, $3, $4, $5, clock_timestamp(), clock_timestamp(),
                           $6::vector)
                   RETURNING id""",
                subject, predicate, obj, source_agent, entry_id,
                _vec_text(embedding) if embedding is not None else None,
            )
            if prev_id is not None:
                await conn.execute(
                    "UPDATE memory_facts SET superseded_by = $2 WHERE id = $1",
                    prev_id, new_id,
                )
            return int(new_id)
