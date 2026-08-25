"""A2A exposure of the closer agent: auto-generated agent card over ASGI.

No network, no DB: the card endpoint must serve without touching runtime env.
"""
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_closer_a2a_app_serves_agent_card():
    from foreman_app.a2a_app import a2a_app

    # A2A routes are mounted during the Starlette lifespan — run it explicitly
    # (uvicorn does this in production; ASGITransport does not).
    async with a2a_app.router.lifespan_context(a2a_app):
        transport = ASGITransport(app=a2a_app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/.well-known/agent-card.json")
            assert r.status_code == 200
            card = r.json()
            assert card["name"] == "closer"
            # the card advertises real capabilities, not an empty shell
            assert card.get("skills") or card.get("description")


@pytest.mark.asyncio
async def test_rpc_paths_require_shared_secret_when_configured(monkeypatch):
    """With A2A_SHARED_SECRET set, discovery stays open but RPC needs the key —
    a public Cloud Run URL must not be a free Vertex-burn endpoint."""
    import importlib
    monkeypatch.setenv("A2A_SHARED_SECRET", "test-key-123")
    import foreman_app.a2a_app as mod
    mod = importlib.reload(mod)

    async with mod.a2a_app.router.lifespan_context(mod.a2a_app):
        transport = ASGITransport(app=mod.a2a_app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # discovery stays open
            card = await client.get("/.well-known/agent-card.json")
            assert card.status_code == 200
            # RPC without the key is refused
            r = await client.post("/", json={"jsonrpc": "2.0", "id": 1,
                                             "method": "message/send", "params": {}})
            assert r.status_code == 401
            # RPC with the key passes the guard (may fail deeper for other
            # reasons, but NOT with 401)
            r2 = await client.post("/", json={"jsonrpc": "2.0", "id": 1,
                                              "method": "message/send", "params": {}},
                                   headers={"X-Foreman-Key": "test-key-123"})
            assert r2.status_code != 401

    monkeypatch.delenv("A2A_SHARED_SECRET")
    importlib.reload(mod)
