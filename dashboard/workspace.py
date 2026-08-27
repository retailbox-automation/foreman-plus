"""Derive the office workspace (properties → visits → facts with provenance)
from memory_facts + gate_journal. Pure functions, no I/O, no schema change:
a property is a grouping over the gate-verified `property` fact."""
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

LABELS = {"manufacture_date": "Manufacture date", "serial_number": "Serial number",
          "equipment_model": "Model", "equipment_brand": "Brand", "equipment_type": "Type",
          "capacity": "Capacity", "refrigerant": "Refrigerant", "access_location": "Location",
          "issue": "Issue", "estimate": "Estimate", "property": "Property",
          "technician": "Technician", "client": "Client"}
EQUIPMENT_PREDS = ["equipment_type", "equipment_brand", "equipment_model", "serial_number",
                   "manufacture_date", "capacity", "refrigerant", "access_location"]
OTHER_PREDS = ["property", "technician", "client", "issue"]
UNKNOWN = "UNKNOWN"


def label(pred: str) -> str:
    return LABELS.get(pred, pred.replace("_", " ").capitalize())


def slugify(address: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return s[:60]


def split_address(address: str) -> tuple[str, str]:
    head, _, tail = address.partition(",")
    return head.strip(), tail.strip()


def _job(subject: str) -> str:
    return subject.split(":", 1)[1] if ":" in subject else subject


def _val(obj: Any) -> Any:
    return obj.get("value") if isinstance(obj, dict) else obj


def _src(obj: Any) -> str | None:
    return obj.get("source") if isinstance(obj, dict) else None


def _iso(ts: Any) -> str | None:
    return ts.isoformat() if isinstance(ts, datetime) else (str(ts) if ts else None)


def _real(row: dict) -> bool:
    return not str(row.get("reason") or "").startswith("verifier error:")


def link_gate_entries(facts: list[dict], journal: list[dict]) -> list[dict]:
    approved = [r for r in journal if r["verdict"] == "approved"]
    out = []
    for f in facts:
        match = None
        for r in sorted(approved, key=lambda r: r["id"], reverse=True):
            p = r["proposal"]
            if (p.get("subject") == f["subject"] and p.get("predicate") == f["predicate"]
                    and _val(p.get("object")) == _val(f["object"])):
                match = r
                break
        g = dict(f)
        g["gate_entry_id"] = match["id"] if match else None
        g["decided_at"] = match["decided_at"] if match else None
        g["verifier_model"] = match["verifier_model"] if match else None
        out.append(g)
    return out


def _by_job(facts: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        d[_job(f["subject"])].append(f)
    return d


def _latest(fs: list[dict], pred: str) -> dict | None:
    c = [f for f in fs if f["predicate"] == pred]
    return max(c, key=lambda f: f["id"]) if c else None


def _visit_date(fs: list[dict]) -> str:
    return min(f["valid_from"] for f in fs).date().isoformat()


def _display_model(fs: list[dict]) -> str | None:
    """'Rheem 82V40-2' from brand + model facts; the brand is prefixed only when
    the model string does not already carry it."""
    model = _latest(fs, "equipment_model")
    if not model or _val(model["object"]) == UNKNOWN:
        return None
    m = str(_val(model["object"])).strip()
    brand = _latest(fs, "equipment_brand")
    if brand and _val(brand["object"]) != UNKNOWN:
        b = str(_val(brand["object"])).strip()
        if b and b.lower() not in m.lower():
            return f"{b} {m}"
    return m


def _estimate_text(raw: Any) -> str:
    try:
        e = json.loads(raw) if isinstance(raw, str) else raw
        parts = ", ".join(e.get("parts") or [])
        return f"{e.get('hours')} h · {parts}" if parts else f"{e.get('hours')} h"
    except Exception:
        return str(raw)


def _fact_view(f: dict) -> dict:
    v = _val(f["object"])
    return {"predicate": f["predicate"], "label": label(f["predicate"]),
            "value": None if v == UNKNOWN else v, "source": _src(f["object"]),
            "agent": f["source_agent"], "ts": _iso(f["valid_from"]),
            "gate_entry_id": f.get("gate_entry_id"),
            "status": "unknown" if v == UNKNOWN else "known"}


def _properties(facts: list[dict]) -> dict[str, dict]:
    """slug -> {"address": raw, "jobs": {job: facts}}"""
    props: dict[str, dict] = {}
    for job, fs in _by_job(facts).items():
        pf = _latest(fs, "property")
        if not pf:
            continue
        raw = str(_val(pf["object"]))
        p = props.setdefault(slugify(raw), {"address": raw, "jobs": {}})
        p["jobs"][job] = fs
    return props


def _job_rows(journal: list[dict], job: str) -> list[dict]:
    return [r for r in journal if _job(r["proposal"].get("subject", "")) == job and _real(r)]


def _summary(props: dict[str, dict], slug: str, journal: list[dict]) -> dict:
    p = props[slug]
    jobs = sorted(p["jobs"].items(), key=lambda kv: _visit_date(kv[1]), reverse=True)
    newest = jobs[0][1]
    addr, city = split_address(p["address"])
    tech = next((_val(_latest(fs, "technician")["object"]) for _, fs in jobs if _latest(fs, "technician")), None)
    client = next((_val(_latest(fs, "client")["object"]) for _, fs in jobs if _latest(fs, "client")), None)
    rejected = [r for job, _ in jobs for r in _job_rows(journal, job) if r["verdict"] == "rejected"]
    unknowns = [f for _, fs in jobs for f in fs if _val(f["object"]) == UNKNOWN]
    state = "needs_confirmation" if rejected else ("unknowns" if unknowns else "calm")
    dm = _display_model(newest)
    bits = [dm] if dm else []
    for pred in ("manufacture_date", "capacity"):
        f = _latest(newest, pred)
        if f and _val(f["object"]) != UNKNOWN:
            bits.append(str(_val(f["object"])))
    return {"id": slug, "address": addr, "city": city, "client": client, "technician": tech,
            "last_visit": _visit_date(newest), "equipment_summary": " · ".join(bits),
            "state": state, "open_questions": len(rejected) + len(unknowns),
            "jobs": [job for job, _ in jobs]}


def group_properties(facts: list[dict], journal: list[dict]) -> list[dict]:
    facts = link_gate_entries(facts, journal)
    props = _properties(facts)
    rows = [_summary(props, slug, journal) for slug in props]
    return sorted(rows, key=lambda r: r["last_visit"], reverse=True)


def _briefing(job: str, fs: list[dict], journal: list[dict]) -> list[dict]:
    lines: list[dict] = []
    tech = _latest(fs, "technician")
    tech_name = _val(tech["object"]) if tech else "technician"
    date = _visit_date(fs)

    def line(text: str, f: dict, predicate: str | None = None):
        text = text[:1].upper() + text[1:]          # equipment_type often arrives lowercase
        lines.append({"text": text, "source": _src(f["object"]) or "unknown source",
                      "agent": f["source_agent"], "ts": _iso(f["valid_from"]),
                      "gate_entry_id": f.get("gate_entry_id"), "job_id": job,
                      "predicate": predicate or f["predicate"]})

    model = _latest(fs, "equipment_model")
    if model:
        etype = _latest(fs, "equipment_type"); brand = _latest(fs, "equipment_brand")
        cap = _latest(fs, "capacity"); loc = _latest(fs, "access_location"); mfg = _latest(fs, "manufacture_date")
        head = " ".join(x for x in [
            str(_val(etype["object"])) if etype and _val(etype["object"]) != UNKNOWN else "Equipment",
            str(_val(brand["object"])) if brand and _val(brand["object"]) != UNKNOWN
            and str(_val(brand["object"])).lower() not in str(_val(model["object"])).lower() else "",
            str(_val(model["object"]))] if x)
        extras = []
        if cap and _val(cap["object"]) != UNKNOWN: extras.append(str(_val(cap["object"])))
        if loc and _val(loc["object"]) != UNKNOWN: extras.append(f"in the {_val(loc['object'])}")
        text = head + (", " + ", ".join(extras) if extras else "")
        if mfg and _val(mfg["object"]) != UNKNOWN:
            text += f" — manufacture date {_val(mfg['object'])}."
            line(text, mfg)
        else:
            line(text + ".", model)
    issue = _latest(fs, "issue")
    if issue:
        line(f"Visit {date} ({tech_name}): {_val(issue['object'])}.", issue)
    est = _latest(fs, "estimate")
    if est:
        line(f"Estimate: {_estimate_text(_val(est['object']))}.", est)
    for f in sorted((f for f in fs if f["predicate"].startswith("deferred")), key=lambda f: f["id"]):
        line(f"Noticed, not repaired: {_val(f['object'])}.", f)
    for f in fs:
        if _val(f["object"]) == UNKNOWN:
            line(f"{label(f['predicate'])} unknown — {_src(f['object']) or 'not captured'}.", f)
    for r in _job_rows(journal, job):
        if r["verdict"] == "rejected":
            p = r["proposal"]
            lines.append({"text": f"Refused: {label(p['predicate'])} = {_val(p['object'])} — {r['reason']}",
                          "source": "write-gate", "agent": r["proposed_by"], "ts": _iso(r["decided_at"]),
                          "gate_entry_id": r["id"], "job_id": job, "predicate": p["predicate"]})
    return lines


def _open_questions(job: str, fs: list[dict], journal: list[dict]) -> list[dict]:
    out = []
    for r in _job_rows(journal, job):
        if r["verdict"] != "rejected":
            continue
        p = r["proposal"]
        cur = _latest(fs, p["predicate"])
        out.append({"kind": "rejected", "job_id": job, "predicate": p["predicate"],
                    "proposed": _val(p["object"]), "reason": r["reason"],
                    "contradicts": ({"value": _val(cur["object"]), "gate_entry_id": cur.get("gate_entry_id"),
                                     "decided_at": _iso(cur.get("decided_at"))} if cur else None),
                    "gate_entry_id": r["id"], "ts": _iso(r["decided_at"]), "proposed_by": r["proposed_by"]})
    for f in fs:
        if _val(f["object"]) == UNKNOWN:
            out.append({"kind": "unknown", "job_id": job, "predicate": f["predicate"],
                        "reason": _src(f["object"]) or "not captured",
                        "gate_entry_id": f.get("gate_entry_id"), "ts": _iso(f["valid_from"])})
    return out


def _equipment(jobs: list[tuple[str, list[dict]]]) -> list[dict]:
    cards: dict[str, dict] = {}
    for _, fs in jobs:                      # jobs newest first → first writer wins per field
        model = _latest(fs, "equipment_model")
        if not model:
            continue
        shown = _display_model(fs) or str(_val(model["object"]))
        key = re.sub(r"[^a-z0-9]+", "", shown.lower())      # "Rheem 82V40-2" == "82V40-2"+brand Rheem
        card = cards.setdefault(key, {"model": shown, "type": "Equipment", "fields": {}})
        etype = _latest(fs, "equipment_type")
        if etype and _val(etype["object"]) != UNKNOWN and card["type"] == "Equipment":
            card["type"] = str(_val(etype["object"]))
        for pred in EQUIPMENT_PREDS:
            f = _latest(fs, pred)
            if f and pred not in card["fields"]:
                card["fields"][pred] = _fact_view(f)
    return list(cards.values())


def property_detail(prop_id: str, facts: list[dict], journal: list[dict]) -> dict | None:
    facts = link_gate_entries(facts, journal)
    props = _properties(facts)
    if prop_id not in props:
        return None
    summary = _summary(props, prop_id, journal)
    jobs = sorted(props[prop_id]["jobs"].items(), key=lambda kv: _visit_date(kv[1]), reverse=True)
    briefing, questions, deferred, visits, docs = [], [], [], [], []
    auto = 0
    for job, fs in jobs:
        briefing += _briefing(job, fs, journal)
        qs = _open_questions(job, fs, journal)
        questions += qs
        rows = _job_rows(journal, job)
        auto += sum(1 for r in rows if r["verdict"] == "approved")
        tech = _latest(fs, "technician"); issue = _latest(fs, "issue"); est = _latest(fs, "estimate")
        for f in fs:
            if f["predicate"].startswith("deferred"):
                deferred.append({"text": str(_val(f["object"])), "technician": _val(tech["object"]) if tech else None,
                                 "ts": _iso(f["valid_from"]), "job_id": job, "gate_entry_id": f.get("gate_entry_id")})
        has_rej = any(r["verdict"] == "rejected" for r in rows)
        visits.append({"job_id": job, "date": _visit_date(fs),
                       "technician": _val(tech["object"]) if tech else None,
                       "issue": _val(issue["object"]) if issue else None,
                       "estimate": _estimate_text(_val(est["object"])) if est else None,
                       "state": "needs_confirmation" if has_rej else ("done" if est else "in_progress"),
                       "open": len(qs), "doc_url": f"/doc/{job}"})
        docs.append({"kind": "homeowner", "job_id": job, "url": f"/doc/{job}"})
        docs.append({"kind": "decider", "job_id": job, "url": f"/doc/{job}?mode=decider"})
        docs.append({"kind": "authorization", "job_id": job, "url": f"/api/closeout/{job}"})
    all_facts = [f for _, fs in jobs for f in fs]
    return {"property": summary, "record_as_of": _iso(max(f["valid_from"] for f in all_facts)),
            "briefing": briefing, "open_questions": questions, "auto_passed": auto,
            "equipment": _equipment(jobs), "deferred": deferred, "visits": visits, "documents": docs}


def job_detail(job_id: str, facts: list[dict], journal: list[dict], closeout: dict | None) -> dict:
    facts = link_gate_entries(facts, journal)
    fs = _by_job(facts).get(job_id, [])
    props = _properties(facts)
    prop = next(({"id": s, "address": split_address(p["address"])[0]} for s, p in props.items() if job_id in p["jobs"]), None)
    groups: dict[str, list] = {"equipment": [], "money": [], "deferred": [], "other": []}
    for f in sorted(fs, key=lambda f: f["id"]):
        view = _fact_view(f)
        if f["predicate"] in EQUIPMENT_PREDS: groups["equipment"].append(view)
        elif f["predicate"] == "estimate":
            view["value"] = _estimate_text(_val(f["object"])); groups["money"].append(view)
        elif f["predicate"].startswith("deferred"): groups["deferred"].append(view)
        else: groups["other"].append(view)
    if closeout and closeout.get("money"):
        for k, v in closeout["money"].items():
            groups["money"].append({"predicate": k, "label": label(k), "value": v, "source": "closeout",
                                    "agent": "closer", "ts": None, "gate_entry_id": None, "status": "known"})
    rows = sorted(_job_rows(journal, job_id), key=lambda r: r["id"], reverse=True)
    journal_view = [{"id": r["id"], "agent": r["proposed_by"], "verdict": r["verdict"],
                     "predicate": r["proposal"].get("predicate"), "value": _val(r["proposal"].get("object")),
                     "reason": r["reason"], "model": r["verifier_model"], "decided_at": _iso(r["decided_at"])} for r in rows]
    return {"job_id": job_id, "property": prop, "facts": groups, "journal": journal_view, "closeout": closeout}
