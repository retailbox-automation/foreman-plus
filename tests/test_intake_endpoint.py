"""POST /api/intake — the technician's phone forwards photo (+ optional voice)
straight into the fleet's /run, same contract as the demo runner and the
glasses bridge. Runs against local Postgres db foreman_core_test_b (see
FOREMAN_TEST_DB_URL / DB_URL below).
"""
import asyncio
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_workspace_endpoints import load_dashboard, seeded  # noqa: F401

DB_URL = os.environ.get("FOREMAN_TEST_DB_URL",
                        "postgresql://oskolamicheal@localhost:5432/foreman_core_test")
REPO = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_intake_accepts_photo_and_audio_and_reports_status(seeded, monkeypatch):
    dm = load_dashboard()
    calls = []

    async def fake_drive(job_id, parts):
        calls.append((job_id, parts))
        dm.intake["jobs"][job_id].update(status="done", reply="ok")

    monkeypatch.setattr(dm, "_drive_intake", fake_drive)
    async with dm.app.router.lifespan_context(dm.app):
        async with AsyncClient(transport=ASGITransport(app=dm.app), base_url="http://t") as c:
            files = {"photo": ("plate.jpg", b"\xff\xd8\xff\xe0fakejpg", "image/jpeg"),
                     "audio": ("v.webm", b"\x1aE\xdf\xa3fakewebm", "audio/webm")}
            data = {"property": "902 Ferncreek Ave, Orlando FL 32806", "technician": "Miguel Torres", "notes": "dryer no heat"}
            r = await c.post("/api/intake", data=data, files=files)
            assert r.status_code == 200 and r.json()["ok"] is True
            job_id = r.json()["job_id"]; assert job_id.startswith("J-T-")
            await asyncio.sleep(0.05)
            assert calls and calls[0][0] == job_id
            parts = calls[0][1]
            assert "902 Ferncreek Ave" in parts[0]["text"] and "Miguel Torres" in parts[0]["text"]
            assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
            assert parts[2]["inlineData"]["mimeType"] == "audio/webm"
            r = await c.get(f"/api/intake/status", params={"job_id": job_id})
            assert r.json()["status"] == "done"
            r = await c.post("/api/intake", data=data, files={"photo": files["photo"]})
            assert r.status_code == 429            # cooldown


@pytest.mark.asyncio
async def test_intake_rejects_missing_photo(seeded):
    dm = load_dashboard()
    async with dm.app.router.lifespan_context(dm.app):
        async with AsyncClient(transport=ASGITransport(app=dm.app), base_url="http://t") as c:
            r = await c.post("/api/intake", data={"property": "x", "technician": "y"})
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_id_token_short_circuits_for_localhost_audience():
    dm = load_dashboard()
    tok = await dm._id_token("http://localhost:9000")
    assert tok == "dev"
