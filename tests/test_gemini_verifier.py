"""Integration tests: real Gemini verifier (needs GEMINI_API_KEY in ../.env).

Run: pytest tests/test_gemini_verifier.py -m integration
"""
import os
from pathlib import Path

import pytest

from foreman_core.gate import Proposal
from foreman_core.verifier import GeminiVerifier

pytestmark = pytest.mark.integration

env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


@pytest.mark.asyncio
async def test_consistent_proposal_is_approved():
    v = GeminiVerifier()
    verdict = await v.verify(
        Proposal(
            subject="equipment:wh-1",
            predicate="serial_number",
            object={"value": "RH2004-556677"},
            proposed_by="intake",
        ),
        existing_facts=[
            {"predicate": "model", "object": {"value": "Rheem 82V40-2"},
             "source_agent": "intake"},
        ],
    )
    assert verdict.approved, verdict.reason
    assert verdict.model  # provenance: which model judged


@pytest.mark.asyncio
async def test_contradictory_proposal_is_rejected_with_reason():
    v = GeminiVerifier()
    verdict = await v.verify(
        Proposal(
            subject="equipment:wh-1",
            predicate="install_year",
            object={"value": 2030},
            proposed_by="estimator",
        ),
        existing_facts=[
            {"predicate": "manufacture_date", "object": {"value": "05/2004"},
             "source_agent": "intake"},
            {"predicate": "condition", "object": {"value": "leaking from bottom, corroded"},
             "source_agent": "intake"},
        ],
    )
    assert not verdict.approved
    assert verdict.reason
