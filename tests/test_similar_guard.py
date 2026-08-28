"""_similar must not hide a misconfigured embedder: it logs a WARNING and returns []."""
import importlib.util
import logging
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def load_dashboard(monkeypatch):
    monkeypatch.setenv("FOREMAN_DB_URL", "postgresql://x@localhost/none")
    spec = importlib.util.spec_from_file_location("dashboard_main_guard", REPO / "dashboard" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_similar_logs_when_embedder_cannot_init(monkeypatch, caplog):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    dm = load_dashboard(monkeypatch)
    facts = [{"subject": "job:J1", "predicate": "issue", "object": {"value": "no hot water"}}]
    with caplog.at_level(logging.WARNING, logger="foreman.dash"):
        out = await dm._similar(store=None, job_id="J1", facts=facts)
    assert out == []
    assert any("similar recall disabled" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_similar_logs_on_runtime_failure(monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    dm = load_dashboard(monkeypatch)

    class BoomStore:
        async def recall(self, *a, **k):
            raise RuntimeError("db down")

    class FakeEmbedder:
        async def embed(self, text, kind="query"):
            return [0.0] * 768

    monkeypatch.setattr(dm, "_embedder_factory", lambda: FakeEmbedder())
    facts = [{"subject": "job:J1", "predicate": "issue", "object": {"value": "no hot water"}}]
    with caplog.at_level(logging.WARNING, logger="foreman.dash"):
        out = await dm._similar(BoomStore(), "J1", facts)
    assert out == []
    assert any("similar recall unavailable for J1" in r.message for r in caplog.records)
