"""Pure derivation of the office workspace (properties -> briefing -> open
questions -> equipment -> visits) from memory_facts + gate_journal. No DB."""
from datetime import datetime, timezone

from dashboard.workspace import (slugify, split_address, link_gate_entries,
                                 group_properties, property_detail, job_detail)

T0 = datetime(2026, 8, 26, 13, 49, tzinfo=timezone.utc)


def fact(id, job, pred, value, source=None, agent="foreman", ts=T0):
    obj = {"value": value}
    if source: obj["source"] = source
    return {"id": id, "subject": f"job:{job}", "predicate": pred, "object": obj,
            "source_agent": agent, "valid_from": ts, "valid_to": None, "ingested_at": ts}


def entry(id, job, pred, value, verdict, reason, by="foreman", ts=T0):
    return {"id": id, "proposed_by": by, "verdict": verdict, "reason": reason,
            "verifier_model": "gemini-3.7-flash", "decided_at": ts, "created_at": ts,
            "proposal": {"subject": f"job:{job}", "predicate": pred, "object": {"value": value}}}


FACTS = [
    fact(1, "J1", "property", "214 Maple Ct, Orlando FL 32806", "intake"),
    fact(2, "J1", "technician", "Alicia Reyes", "intake"),
    fact(3, "J1", "client", "Ray Okafor", "intake"),
    fact(4, "J1", "equipment_model", "Rheem 82V40-2", "nameplate photo"),
    fact(5, "J1", "manufacture_date", "05/2004", "nameplate photo"),
    fact(6, "J1", "serial_number", "UNKNOWN", "plate unreadable"),
    fact(7, "J1", "issue", "no hot water since yesterday", "technician voice"),
    fact(8, "J1", "estimate", '{"job":"J1","hours":2,"parts":["lower element","thermostat"]}', "estimator", agent="estimator"),
    fact(9, "J2", "issue", "orphan job without property"),
]
JOURNAL = [
    entry(101, "J1", "equipment_model", "Rheem 82V40-2", "approved", "ok"),
    entry(104, "J1", "manufacture_date", "05/2004", "approved", "ok"),
    entry(106, "J1", "serial_number", "UNKNOWN", "approved", "ok"),
    entry(107, "J1", "issue", "no hot water since yesterday", "approved", "ok"),
    entry(108, "J1", "manufacture_date", "2022", "rejected",
          "The proposed manufacture date contradicts the existing recorded manufacture date", by="estimator"),
    entry(109, "J1", "estimate", '{"job":"J1","hours":2,"parts":["lower element","thermostat"]}', "approved", "ok", by="estimator"),
    entry(110, "J1", "issue", "x", "rejected", "verifier error: 403"),
]


def test_slugify_and_split():
    assert slugify("214 Maple Ct, Orlando FL 32806") == "214-maple-ct-orlando-fl-32806"
    assert split_address("214 Maple Ct, Orlando FL 32806") == ("214 Maple Ct", "Orlando FL 32806")
    assert split_address("No comma here") == ("No comma here", "")


def test_link_gate_entries_attaches_latest_approved_row():
    linked = {f["predicate"]: f for f in link_gate_entries(FACTS, JOURNAL)}
    assert linked["manufacture_date"]["gate_entry_id"] == 104
    assert linked["serial_number"]["gate_entry_id"] == 106
    assert linked["technician"]["gate_entry_id"] is None   # no journal row in fixture


def test_group_properties_excludes_orphans_and_derives_state():
    props = group_properties(FACTS, JOURNAL)
    assert [p["id"] for p in props] == ["214-maple-ct-orlando-fl-32806"]
    p = props[0]
    assert p["address"] == "214 Maple Ct" and p["city"] == "Orlando FL 32806"
    assert p["client"] == "Ray Okafor" and p["technician"] == "Alicia Reyes"
    assert p["state"] == "needs_confirmation"
    assert p["open_questions"] == 2          # 1 rejected (403 row excluded) + 1 UNKNOWN
    assert p["jobs"] == ["J1"]
    assert p["equipment_summary"].startswith("Rheem 82V40-2")


def test_property_detail_briefing_open_questions_equipment_visits():
    d = property_detail("214-maple-ct-orlando-fl-32806", FACTS, JOURNAL)
    texts = [b["text"] for b in d["briefing"]]
    assert any("Rheem 82V40-2" in t and "05/2004" in t for t in texts)
    assert any(t.startswith("Visit 2026-08-26 (Alicia Reyes): no hot water") for t in texts)
    assert any(t.startswith("Estimate: 2 h · lower element, thermostat") for t in texts)
    assert any("Serial number unknown — plate unreadable" in t for t in texts)
    assert all(b["source"] and b["gate_entry_id"] is not None for b in d["briefing"] if b["predicate"] != "technician")
    rejected = [q for q in d["open_questions"] if q["kind"] == "rejected"][0]
    assert rejected["proposed"] == "2022" and rejected["contradicts"]["value"] == "05/2004"
    assert rejected["contradicts"]["gate_entry_id"] == 104 and rejected["gate_entry_id"] == 108
    assert "verifier error" not in " ".join(q["reason"] for q in d["open_questions"])
    unknown = [q for q in d["open_questions"] if q["kind"] == "unknown"][0]
    assert unknown["predicate"] == "serial_number" and unknown["reason"] == "plate unreadable"
    assert d["auto_passed"] == 5
    eq = d["equipment"][0]
    assert eq["model"] == "Rheem 82V40-2"
    assert eq["fields"]["serial_number"]["status"] == "unknown"
    assert eq["fields"]["manufacture_date"]["source"] == "nameplate photo"
    v = d["visits"][0]
    assert v == {"job_id": "J1", "date": "2026-08-26", "technician": "Alicia Reyes",
                 "issue": "no hot water since yesterday", "estimate": "2 h · lower element, thermostat",
                 "state": "needs_confirmation", "open": 2, "doc_url": "/doc/J1"}
    assert d["documents"][0]["url"] == "/doc/J1"


def test_property_detail_unknown_id_returns_none():
    assert property_detail("nope", FACTS, JOURNAL) is None


def test_job_detail_groups_facts_and_journal():
    j = job_detail("J1", FACTS, JOURNAL, closeout=None)
    assert j["property"]["id"] == "214-maple-ct-orlando-fl-32806"
    assert {f["predicate"] for f in j["facts"]["equipment"]} == {"equipment_model", "manufacture_date", "serial_number"}
    assert j["facts"]["money"][0]["label"] == "Estimate"
    assert [e["id"] for e in j["journal"]][:2] == [109, 108]      # newest first, 403 row excluded
    assert j["journal"][1]["reason"].startswith("The proposed manufacture date")


def test_brand_is_prefixed_when_model_lacks_it():
    facts = FACTS + [fact(10, "J1", "equipment_brand", "Rheem", "nameplate photo")]
    facts = [f if not (f["predicate"] == "equipment_model" and f["subject"] == "job:J1") else
             {**f, "object": {"value": "82V40-2", "source": "nameplate photo"}} for f in facts]
    props = group_properties(facts, JOURNAL)
    assert props[0]["equipment_summary"].startswith("Rheem 82V40-2")
    d = property_detail("214-maple-ct-orlando-fl-32806", facts, JOURNAL)
    assert d["equipment"][0]["model"] == "Rheem 82V40-2"
    # brand already inside the model string is not duplicated
    d2 = property_detail("214-maple-ct-orlando-fl-32806", FACTS + [fact(10, "J1", "equipment_brand", "Rheem")], JOURNAL)
    assert d2["equipment"][0]["model"] == "Rheem 82V40-2"
