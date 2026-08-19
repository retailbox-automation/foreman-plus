"""Backfill embeddings for current facts written before the recall layer.

Usage: .venv/bin/python scripts/backfill_embeddings.py "$DB_URL"
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])

from foreman_app.foreman_core.db import create_pool  # noqa: E402
from foreman_app.foreman_core.embedder import GeminiEmbedder  # noqa: E402
from foreman_app.foreman_core.memory import _vec_text  # noqa: E402


async def main(db_url: str) -> None:
    pool = await create_pool(db_url)
    emb = GeminiEmbedder()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, subject, predicate, object FROM memory_facts"
            " WHERE valid_to IS NULL AND embedding IS NULL ORDER BY id"
        )
    print(f"{len(rows)} facts to backfill")
    done = 0
    for r in rows:
        text = f"{r['subject']} {r['predicate']}: {r['object'].get('value')}"
        vec = await emb.embed(text, kind="document")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE memory_facts SET embedding = $2::vector WHERE id = $1",
                r["id"], _vec_text(vec),
            )
        done += 1
    remaining = None
    async with pool.acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT count(*) FROM memory_facts WHERE valid_to IS NULL AND embedding IS NULL")
    print(f"backfilled {done}; remaining NULL: {remaining}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
