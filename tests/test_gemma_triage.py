"""Gemma triage — the advisory labeling layer over open questions.

No live model here: the transport is injected. What must hold is the contract:
strict parsing (garbage → no labels, never an error), caching (one call per
unseen question set), and fail-open degradation (transport failure → empty
labels, page unchanged).
"""
import pytest

from dashboard.gemma_triage import (
    GEMMA_MODEL_SHORT, _cache, parse_labels, triage_open_questions,
)


def _q(gid, kind="rejected", predicate="manufacture_date", **kw):
    base = {"gate_entry_id": gid, "kind": kind, "predicate": predicate,
            "proposed": "2022", "reason": "contradicts existing fact"}
    base.update(kw)
    return base


def _response(text):
    return {"choices": [{"message": {"content": text}}]}


@pytest.fixture(autouse=True)
def clean_cache():
    _cache.clear()
    yield
    _cache.clear()


# ------------------------------------------------------------- parse_labels

def test_parse_good_array():
    got = parse_labels('[{"i": 0, "category": "safety", "urgency": "now"}]', 1)
    assert got == {0: {"category": "safety", "urgency": "now"}}


def test_parse_tolerates_prose_and_fence():
    text = 'Sure! ```json\n[{"i": 0, "category": "data-gap", "urgency": "next-visit"}]\n```'
    assert parse_labels(text, 1)[0]["category"] == "data-gap"


def test_parse_garbage_is_empty():
    assert parse_labels("no json here", 3) == {}
    assert parse_labels("", 3) == {}
    assert parse_labels(None, 3) == {}


def test_parse_drops_invented_categories_and_bad_indices():
    text = ('[{"i": 0, "category": "vibes", "urgency": "now"},'
            ' {"i": 7, "category": "safety", "urgency": "now"},'
            ' {"i": 1, "category": "safety", "urgency": "someday"},'
            ' {"i": 1, "category": "billing", "urgency": "paperwork-only"}]')
    assert parse_labels(text, 2) == {1: {"category": "billing", "urgency": "paperwork-only"}}


# --------------------------------------------------- triage_open_questions

@pytest.mark.asyncio
async def test_labels_keyed_by_gate_entry_id():
    async def post(payload):
        return _response('[{"i": 0, "category": "dispute", "urgency": "now"},'
                         ' {"i": 1, "category": "data-gap", "urgency": "next-visit"}]')
    out = await triage_open_questions(
        [_q(150), _q(93, kind="unknown", predicate="serial_number")], post=post)
    assert out["model"] == GEMMA_MODEL_SHORT
    assert out["labels"]["150"] == {"category": "dispute", "urgency": "now"}
    assert out["labels"]["93"] == {"category": "data-gap", "urgency": "next-visit"}


@pytest.mark.asyncio
async def test_second_call_is_served_from_cache():
    calls = []

    async def post(payload):
        calls.append(payload)
        return _response('[{"i": 0, "category": "safety", "urgency": "now"}]')

    qs = [_q(150)]
    await triage_open_questions(qs, post=post)
    out = await triage_open_questions(qs, post=post)
    assert len(calls) == 1
    assert out["labels"]["150"]["category"] == "safety"


@pytest.mark.asyncio
async def test_transport_failure_degrades_to_no_labels():
    async def post(payload):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    out = await triage_open_questions([_q(150)], post=post)
    assert out["labels"] == {}


@pytest.mark.asyncio
async def test_question_without_gate_entry_never_reaches_the_model():
    calls = []

    async def post(payload):
        calls.append(payload)
        return _response("[]")

    out = await triage_open_questions([_q(None)], post=post)
    assert calls == []          # nothing addressable → nothing to ask
    assert out["labels"] == {}


@pytest.mark.asyncio
async def test_prompt_carries_both_kinds_verbatim():
    seen = {}

    async def post(payload):
        seen["content"] = payload["messages"][0]["content"]
        return _response("[]")

    await triage_open_questions(
        [_q(1, reason="Proposal contradicts existing manufacture date"),
         _q(2, kind="unknown", predicate="capacity", reason="plate unreadable")],
        post=post)
    assert "REFUSED claim" in seen["content"]
    assert "UNKNOWN field: capacity" in seen["content"]
    assert "plate unreadable" in seen["content"]
