"""Bi-temporal shared memory over Postgres (asyncpg)."""
import datetime as dt
from typing import Any

import asyncpg


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
        self, subject: str, as_of: dt.datetime | None = None
    ) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            if as_of is None:
                rows = await conn.fetch(
                    "SELECT * FROM memory_facts WHERE subject = $1 AND valid_to IS NULL"
                    " ORDER BY id", subject,
                )
            else:
                rows = await conn.fetch(
                    """SELECT * FROM memory_facts
                       WHERE subject = $1 AND valid_from <= $2
                         AND (valid_to IS NULL OR valid_to > $2)
                       ORDER BY id""",
                    subject, as_of,
                )
        return [dict(r) for r in rows]

    async def fact_history(self, subject: str, predicate: str) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM memory_facts WHERE subject = $1 AND predicate = $2 ORDER BY id",
                subject, predicate,
            )
        return [dict(r) for r in rows]

    async def gate_journal(self, subject: str | None = None) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            if subject is None:
                rows = await conn.fetch("SELECT * FROM gate_journal ORDER BY id")
            else:
                rows = await conn.fetch(
                    "SELECT * FROM gate_journal WHERE proposal ->> 'subject' = $1 ORDER BY id",
                    subject,
                )
        return [dict(r) for r in rows]

    async def insert_fact(
        self, subject: str, predicate: str, obj: dict, source_agent: str, gate_entry_id: int
    ) -> int:
        """Insert a fact, superseding the current one for (subject, predicate)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                prev_id = await conn.fetchval(
                    """SELECT id FROM memory_facts
                       WHERE subject = $1 AND predicate = $2 AND valid_to IS NULL
                       FOR UPDATE""",
                    subject, predicate,
                )
                new_id = await conn.fetchval(
                    """INSERT INTO memory_facts
                         (subject, predicate, object, source_agent, gate_entry_id)
                       VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                    subject, predicate, obj, source_agent, gate_entry_id,
                )
                if prev_id is not None:
                    await conn.execute(
                        """UPDATE memory_facts
                           SET valid_to = now(), superseded_by = $2 WHERE id = $1""",
                        prev_id, new_id,
                    )
        return new_id
