"""(Re)embed current facts for semantic recall.

Default: only facts whose embedding is NULL (facts written before the recall
layer existed). `--all`: re-embed EVERY current fact — required after an
embedding-model switch, because vectors from two models don't share a space
and mixing them silently corrupts recall ranking.

Usage:
  .venv/bin/python scripts/backfill_embeddings.py "$DB_URL" [--all] [--dry-run]
Auth follows .env (Vertex/ADC or key) via the shared client factory.
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

from foreman_app.foreman_core.db import create_pool  # noqa: E402
from foreman_app.foreman_core.embedder import EMBED_MODEL, GeminiEmbedder  # noqa: E402
from foreman_app.foreman_core.memory import _vec_text  # noqa: E402


async def main(db_url: str, everything: bool, dry_run: bool) -> None:
    pool = await create_pool(db_url)
    emb = GeminiEmbedder()
    where = "valid_to IS NULL" + ("" if everything else " AND embedding IS NULL")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, subject, predicate, object FROM memory_facts WHERE {where} ORDER BY id")
    print(f"{len(rows)} facts to embed with {EMBED_MODEL} (mode={'all' if everything else 'null-only'})")
    if dry_run:
        await pool.close()
        return
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
        if done % 10 == 0:
            print(f"  {done}/{len(rows)}")
    async with pool.acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT count(*) FROM memory_facts WHERE valid_to IS NULL AND embedding IS NULL")
    print(f"embedded {done}; remaining NULL: {remaining}")
    await pool.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    asyncio.run(main(args[0], "--all" in flags, "--dry-run" in flags))
