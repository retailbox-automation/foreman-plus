"""asyncpg pool + schema bootstrap for the Foreman+ core."""
import json
from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool(db_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(db_url, init=_init_conn, min_size=1, max_size=5)


async def apply_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text())
