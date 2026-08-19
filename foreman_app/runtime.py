"""Lazy bootstrap of the shared-memory environment (pool, store, write-gate).

Created on first tool call: ADK loads agent modules synchronously, so the async
pool cannot be built at import time. FOREMAN_DB_URL selects the Postgres target
(local dev / Cloud SQL socket on Cloud Run).
"""
import asyncio
import os

from .foreman_core.db import apply_schema, create_pool
from .foreman_core.embedder import GeminiEmbedder
from .foreman_core.gate import WriteGate
from .foreman_core.memory import MemoryStore
from .foreman_core.verifier import GeminiVerifier

FLEET = [
    ("foreman", "Routes repair requests, records reported facts"),
    ("estimator", "Estimates repair scope and cost"),
]

_lock: asyncio.Lock | None = None
_env: tuple[MemoryStore, WriteGate] | None = None
_loop: asyncio.AbstractEventLoop | None = None
_embedder: GeminiEmbedder | None = None


def get_embedder() -> GeminiEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = GeminiEmbedder()  # lazy: needs GOOGLE_API_KEY at call time
    return _embedder


async def get_env() -> tuple[MemoryStore, WriteGate]:
    """The pool and lock are bound to the event loop that created them; if we
    are called from a different loop (test runners, re-created server loops),
    rebuild instead of crashing on cross-loop reuse."""
    global _lock, _env, _loop
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _lock, _env, _loop = asyncio.Lock(), None, loop
    assert _lock is not None
    async with _lock:
        if _env is None:
            pool = await create_pool(os.environ["FOREMAN_DB_URL"])
            await apply_schema(pool)
            store = MemoryStore(pool)
            for name, desc in FLEET:
                await store.register_agent(name, version="0.2", description=desc)
            _env = (store, WriteGate(store, GeminiVerifier(), embedder=get_embedder()))
    return _env
