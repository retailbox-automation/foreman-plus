"""Closeout agent core: verified-facts document built ONLY from gated memory.

The closeout is the fleet's deal-facing exit: homeowner HTML, absent-decider
HTML, and an authorization JSON (home-warranty lane) — every number traceable
to an approved gate entry, every gap an honest UNKNOWN, never a plausible fill.

Runs against local Postgres db `foreman_core_test` (createdb foreman_core_test).
"""
import json

import pytest
import pytest_asyncio

from foreman_app.foreman_core.db import create_pool, apply_schema
from foreman_app.foreman_core.memory import MemoryStore
from foreman_app.foreman_core.gate import WriteGate, Proposal, Verdict
from foreman_app.foreman_core.closeout import (
    build_closeout,
    render_homeowner_html,
    render_decider_html,
    authorization_json,
)

DB_URL = "postgresql://oskolamicheal@localhost:5432/foreman_core_test"

JOB = "J-CLOSE1"
SUBJ = f"job:{JOB}"


class ApproveAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=True, reason="fake: ok")


class RejectAll:
    async def verify(self, proposal, existing_facts):
        return Verdict(approved=False, reason="contradicts plate date 05/2004; "
                                              "source is an unverified verbal claim")


@pytest_asyncio.fixture
async def store():
    pool = await create_pool(DB_URL)
    async with pool.acquire() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS memory_facts, gate_journal, agents CASCADE"
        )
    await apply_schema(pool)
    s = MemoryStore(pool)
    await s.register_agent("foreman", version="0.1", description="test")
    yield s
    await pool.close()


async def seed_job(store, *, refrigerant=None, parts=None, extra=None,
                   with_estimate=True, equipment_type=None):
    """Approve a typical fact set for JOB; returns {predicate: gate_entry_id}."""
    gate = WriteGate(store, verifier=ApproveAll())
    facts = {
        "equipment_model": "Rheem 82V40-2",
        "manufacture_date": "05/2004",
        "issue": "no hot water, heats barely",
    }
    if refrigerant:
        facts["refrigerant"] = refrigerant
    if equipment_type:
        facts["equipment_type"] = equipment_type
    if with_estimate:
        facts["estimate"] = json.dumps(
            {"job": JOB, "hours": 3, "parts": parts or ["thermostat"]})
    facts.update(extra or {})
    ids = {}
    for pred, value in facts.items():
        entry = await gate.submit(Proposal(
            subject=SUBJ, predicate=pred, object={"value": value},
            proposed_by="foreman"))
        assert entry.verdict == "approved"
        ids[pred] = entry.id
    return ids


# ---------------------------------------------------------------- facts & provenance

@pytest.mark.asyncio
async def test_closeout_uses_only_approved_facts_with_provenance(store):
    ids = await seed_job(store)
    # the poisoned homeowner claim is REJECTED by the gate
    reject_gate = WriteGate(store, verifier=RejectAll())
    rejected = await reject_gate.submit(Proposal(
        subject=SUBJ, predicate="equipment_age",
        object={"value": "a couple of years old"}, proposed_by="foreman"))
    assert rejected.verdict == "rejected"

    c = await build_closeout(store, JOB)

    assert c["job_id"] == JOB
    assert c["equipment"]["equipment_model"]["value"] == "Rheem 82V40-2"
    # provenance: every included fact points to its admitting gate entry
    assert c["equipment"]["equipment_model"]["gate_entry_id"] == ids["equipment_model"]
    # the rejected claim is listed as rejected — and its value is NOT a fact
    assert any(r["predicate"] == "equipment_age" for r in c["rejected"])
    included_values = json.dumps(c["equipment"]) + json.dumps(c["estimate"])
    assert "a couple of years old" not in included_values


@pytest.mark.asyncio
async def test_rejected_value_never_appears_in_homeowner_html(store):
    await seed_job(store)
    reject_gate = WriteGate(store, verifier=RejectAll())
    await reject_gate.submit(Proposal(
        subject=SUBJ, predicate="equipment_age",
        object={"value": "a couple of years old"}, proposed_by="foreman"))

    c = await build_closeout(store, JOB)
    html = render_homeowner_html(c)
    assert "a couple of years old" not in html
    # the plate-read manufacture date IS shown
    assert "05/2004" in html


# ---------------------------------------------------------------- honest unknown

@pytest.mark.asyncio
async def test_missing_serial_is_honest_unknown_not_a_fill(store):
    await seed_job(store)  # no serial_number seeded

    c = await build_closeout(store, JOB)
    assert "serial_number" in c["unknowns"]
    html = render_homeowner_html(c)
    assert "Unknown" in html  # shown, not silently dropped or invented


@pytest.mark.asyncio
async def test_fact_source_kind_is_carried(store):
    # voice-added serial carries its source kind (voice, not plate)
    await seed_job(store, extra={})
    gate = WriteGate(store, verifier=ApproveAll())
    await gate.submit(Proposal(
        subject=SUBJ, predicate="serial_number",
        object={"value": "RH04051234", "source": "voice, not plate"},
        proposed_by="foreman"))

    c = await build_closeout(store, JOB)
    assert c["equipment"]["serial_number"]["source"] == "voice, not plate"
    html = render_homeowner_html(c)
    assert "voice, not plate" in html


# ---------------------------------------------------------------- refrigerant flags

@pytest.mark.asyncio
async def test_a2l_refrigerant_raises_flag_and_recovery_line(store):
    await seed_job(store, refrigerant="R-454B")

    c = await build_closeout(store, JOB)
    assert c["flags"]["a2l"] is True
    html = render_homeowner_html(c)
    assert "A2L" in html
    assert "recovery documentation" in html.lower()


@pytest.mark.asyncio
async def test_r410a_compressor_failure_flags_replacement_conversation(store):
    await seed_job(store, refrigerant="R-410A", parts=["compressor"])

    c = await build_closeout(store, JOB)
    assert c["flags"]["a2l"] is False
    assert c["flags"]["replacement_conversation"] is True


# ---------------------------------------------------------------- money split

@pytest.mark.asyncio
async def test_money_sections_are_separated_and_fail_closed(store):
    await seed_job(store, parts=["compressor"])

    c = await build_closeout(store, JOB)
    money = c["money"]
    # (1) parts warranty is ADVISORY, registration status honest-unknown
    assert money["parts_warranty"]["status"] == "advisory"
    assert money["parts_warranty"]["registration_status"] == "UNKNOWN"
    # (2) labor + service call are billable, never merged into warranty
    assert money["labor"]["billable"] is True
    # (3) core charge present because a compressor is in parts
    assert money["core_charge"]["applies"] is True
    # diagnostic fee is a policy field, not a hardcoded rule
    assert "credited_toward_repair" in money["diagnostic_fee"]

    html = render_homeowner_html(c)
    assert "advisory" in html.lower()
    assert "supply house" in html.lower()
    assert "core charge" in html.lower()


@pytest.mark.asyncio
async def test_no_core_charge_without_compressor(store):
    await seed_job(store, parts=["thermostat"])
    c = await build_closeout(store, JOB)
    assert c["money"]["core_charge"]["applies"] is False


# ---------------------------------------------------------------- compliance

@pytest.mark.asyncio
async def test_compliance_block_defaults_to_unknown_not_invented(store):
    await seed_job(store)
    c = await build_closeout(store, JOB)
    assert c["compliance"]["contractor_license"] == "UNKNOWN"
    assert c["compliance"]["epa_608"] == "UNKNOWN"
    html = render_homeowner_html(c)
    assert "license" in html.lower()


@pytest.mark.asyncio
async def test_water_heater_gets_code_notes_and_permit_line(store):
    await seed_job(store, equipment_type="water heater")
    c = await build_closeout(store, JOB)
    notes = " ".join(c["compliance"]["code_notes"]).lower()
    assert "t&p" in notes
    assert "expansion tank" in notes
    assert "permit" in notes


# ---------------------------------------------------------------- deferred findings

@pytest.mark.asyncio
async def test_deferred_findings_get_their_own_section(store):
    await seed_job(store, extra={
        "deferred_finding_pan": "rusted drain pan, not in current scope"})
    c = await build_closeout(store, JOB)
    assert any("rusted drain pan" in f["value"] for f in c["deferred_findings"])
    html = render_homeowner_html(c)
    assert "rusted drain pan" in html


# ---------------------------------------------------------------- estimate

@pytest.mark.asyncio
async def test_estimate_json_is_parsed(store):
    await seed_job(store, parts=["thermostat"])
    c = await build_closeout(store, JOB)
    assert c["estimate"]["hours"] == 3
    assert c["estimate"]["parts"] == ["thermostat"]


@pytest.mark.asyncio
async def test_missing_estimate_is_unknown(store):
    await seed_job(store, with_estimate=False)
    c = await build_closeout(store, JOB)
    assert c["estimate"] is None
    assert "estimate" in c["unknowns"]


# ---------------------------------------------------------------- renders

@pytest.mark.asyncio
async def test_decider_render_carries_validity_and_evidence(store):
    await seed_job(store)
    c = await build_closeout(store, JOB)
    html = render_decider_html(c)
    assert c["quote_valid_until"][:10] in html  # date visible
    assert "evidence" in html.lower() or "photo" in html.lower()


@pytest.mark.asyncio
async def test_authorization_json_is_serializable_with_provenance(store):
    ids = await seed_job(store)
    c = await build_closeout(store, JOB)
    payload = authorization_json(c)
    dumped = json.dumps(payload)  # must be JSON-serializable as-is
    assert payload["job_id"] == JOB
    assert payload["verified_facts"]["equipment_model"]["gate_entry_id"] == \
        ids["equipment_model"]
    assert "advisory" in dumped  # warranty stance travels with the payload


# ---------------------------------------------------------------- review fixes

@pytest.mark.asyncio
async def test_refrigerant_flags_fire_on_unprefixed_values(store):
    # techs say "410A" / "454b" — normalizer must still light the flags
    await seed_job(store, refrigerant="410A", parts=["compressor"])
    c = await build_closeout(store, JOB)
    assert c["flags"]["replacement_conversation"] is True


@pytest.mark.asyncio
async def test_a2l_flag_fires_on_lowercase_unprefixed(store):
    await seed_job(store, refrigerant="454b")
    c = await build_closeout(store, JOB)
    assert c["flags"]["a2l"] is True


@pytest.mark.asyncio
async def test_non_dict_estimate_json_degrades_to_unknown(store):
    # a gate-approved estimate that parses to a JSON scalar must NOT 500 the
    # public /doc endpoint — it degrades to the honest-unknown path
    await seed_job(store, with_estimate=False, extra={"estimate": "42"})
    c = await build_closeout(store, JOB)
    assert c["estimate"] is None
    assert "estimate" in c["unknowns"]
    render_homeowner_html(c)  # must not raise
