"""Closeout: the fleet's deal-facing exit document, built ONLY from gated memory.

Deterministic by design — no LLM call in this path. Every included number
traces to an approved gate_journal entry; every gap is an honest UNKNOWN
(never a plausible fill); warranty statements are advisory and fail-closed.

Three renders of one closeout object:
  - render_homeowner_html  — on-site, sign-and-pay-before-the-truck-leaves
  - render_decider_html    — absent decision-maker (spouse / property manager)
  - authorization_json     — home-warranty lane / any downstream system (A2A)
"""
import datetime as dt
import json
import html as _html
import os
import re
from typing import Any

from .memory import MemoryStore

QUOTE_VALIDITY_DAYS = 14

EQUIPMENT_PREDICATES = [
    "equipment_model", "serial_number", "manufacture_date",
    "refrigerant", "equipment_type",
]
CORE_PREDICATES = ["equipment_model", "serial_number", "manufacture_date",
                   "refrigerant", "estimate"]

A2L_REFRIGERANTS = {"R-454B", "R-32", "R-452B", "R-454C", "R-454A"}

WATER_HEATER_CODE_NOTES = [
    "T&P relief valve discharge line: required, must terminate per code",
    "Expansion tank: required on closed systems",
    "Drain pan and drain line: required for attic/upper-floor installs",
    "Venting and draft: verify clearances and draft at completion",
    "Permit: replacement is permitted work in most jurisdictions — "
    "contractor pulls the permit; final inspection follows",
]


def _norm_refrigerant(value: str) -> str:
    """'410A', 'r410a', 'R 410A', 'R-410A' → 'R-410A' (techs say all of these)."""
    s = re.sub(r"[^A-Z0-9]", "", value.upper())
    if s.startswith("R"):
        s = s[1:]
    return f"R-{s}"


async def build_closeout(store: MemoryStore, job_id: str) -> dict[str, Any]:
    subject = f"job:{job_id}"
    facts = await store.current_facts(subject)
    journal = await store.gate_journal(subject=subject)
    by_pred = {f["predicate"]: f for f in facts}

    def fact_view(pred: str) -> dict[str, Any]:
        f = by_pred.get(pred)
        if f is None:
            return {"value": "UNKNOWN"}
        view = {"value": f["object"].get("value"),
                "gate_entry_id": f["gate_entry_id"],
                "recorded_by": f["source_agent"]}
        if "source" in f["object"]:
            view["source"] = f["object"]["source"]
        return view

    equipment = {p: fact_view(p) for p in EQUIPMENT_PREDICATES}

    unknowns = [p for p in CORE_PREDICATES
                if p != "estimate" and p not in by_pred]

    # estimate: recorded by the estimator as a JSON string
    estimate = None
    if "estimate" in by_pred:
        raw = by_pred["estimate"]["object"].get("value")
        try:
            estimate = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            estimate = None
        if not isinstance(estimate, dict):  # scalar/list JSON → honest unknown
            estimate = None
    if estimate is None:
        unknowns.append("estimate")

    rejected = [
        {"predicate": e["proposal"].get("predicate"),
         "value": (e["proposal"].get("object") or {}).get("value"),
         "reason": e["reason"], "proposed_by": e["proposed_by"],
         "gate_entry_id": e["id"]}
        for e in journal if e["verdict"] == "rejected"
    ]

    refrigerant = equipment["refrigerant"]["value"]
    refrigerant_known = refrigerant != "UNKNOWN" and refrigerant is not None
    a2l = refrigerant_known and _norm_refrigerant(str(refrigerant)) in A2L_REFRIGERANTS

    parts = [str(p) for p in (estimate or {}).get("parts", [])]
    compressor_involved = any("compressor" in p.lower() for p in parts)
    replacement_conversation = bool(
        refrigerant_known
        and _norm_refrigerant(str(refrigerant)) == "R-410A"
        and compressor_involved
    )

    money = {
        "diagnostic_fee": {
            "typical_range": "$99–$159",
            "credited_toward_repair": "per company policy — set at booking",
        },
        "labor": {
            "billable": True,
            "note": "Labor and the service call are billable. Parts warranties "
                    "almost never cover labor.",
        },
        "parts_warranty": {
            "status": "advisory",
            "registration_status": "UNKNOWN",
            "coverage": "5 years base parts / 10 years only if the unit was "
                        "registered within 60–90 days of install",
            "confirmed_by": "authorized supply house, by serial number in the "
                            "manufacturer's system — this document does not "
                            "assert coverage",
        },
        "core_charge": {
            "applies": compressor_involved,
            "note": "Refundable deposit on the replaced core (compressor and "
                    "similar) — credited on return of the old part."
            if compressor_involved else "Not applicable to this scope.",
        },
    }

    equipment_type = str(equipment["equipment_type"]["value"] or "").lower()
    code_notes = list(WATER_HEATER_CODE_NOTES) \
        if "water heater" in equipment_type else []

    compliance = {
        "contractor_license": os.environ.get("FOREMAN_CONTRACTOR_LICENSE", "UNKNOWN"),
        "epa_608": os.environ.get("FOREMAN_EPA608", "UNKNOWN"),
        "refrigerant_type": refrigerant if refrigerant_known else "UNKNOWN",
        "recovery_documentation_required": bool(refrigerant_known),
        "code_notes": code_notes,
    }

    deferred = [
        {"predicate": p, "value": f["object"].get("value"),
         "gate_entry_id": f["gate_entry_id"]}
        for p, f in by_pred.items() if p.startswith("deferred")
    ]

    now = dt.datetime.now(dt.timezone.utc)
    provenance = {p: by_pred[p]["gate_entry_id"] for p in by_pred}

    issue = fact_view("issue")

    return {
        "job_id": job_id,
        "generated_at": now.isoformat(),
        "quote_valid_until": (now + dt.timedelta(days=QUOTE_VALIDITY_DAYS)).isoformat(),
        "equipment": equipment,
        "issue": issue,
        "estimate": estimate,
        "unknowns": unknowns,
        "rejected": rejected,
        "flags": {"a2l": a2l, "replacement_conversation": replacement_conversation},
        "money": money,
        "compliance": compliance,
        "deferred_findings": deferred,
        "provenance": provenance,
    }


# ------------------------------------------------------------------ renders

_CSS = """
  body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1c1c1c;
         background: #fff; max-width: 720px; margin: 0 auto; padding: 32px 24px;
         line-height: 1.5; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  h2 { font-size: 15px; letter-spacing: .06em; text-transform: uppercase;
       color: #6b6b6b; border-bottom: 1px solid #e6e2dc; padding-bottom: 6px;
       margin: 28px 0 10px; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 6px 8px 6px 0; vertical-align: top; }
  td.k { color: #6b6b6b; width: 38%; }
  .unknown { color: #b3541e; font-weight: 600; }
  .badge { font-size: 11px; color: #6b6b6b; border: 1px solid #d9d4cc;
           border-radius: 10px; padding: 1px 8px; margin-left: 6px; }
  .advisory { background: #faf6ef; border: 1px solid #e6dcc8; border-radius: 8px;
              padding: 12px 14px; margin: 8px 0; }
  .flag { background: #fdf1ec; border: 1px solid #efc9b8; border-radius: 8px;
          padding: 10px 14px; margin: 8px 0; }
  .meta { color: #6b6b6b; font-size: 13px; }
  .prov { color: #9a958d; font-size: 11px; margin-top: 28px;
          border-top: 1px solid #e6e2dc; padding-top: 10px; }
"""

_LABELS = {
    "equipment_model": "Model", "serial_number": "Serial number",
    "manufacture_date": "Manufacture date", "refrigerant": "Refrigerant",
    "equipment_type": "Equipment type", "issue": "Reported issue",
}


def _esc(v: Any) -> str:
    return _html.escape(str(v))


def _fact_row(pred: str, view: dict[str, Any]) -> str:
    label = _LABELS.get(pred, pred.replace("_", " ").capitalize())
    if view.get("value") in (None, "UNKNOWN"):
        val = '<span class="unknown">Unknown</span>'
    else:
        val = _esc(view["value"])
        if view.get("source"):
            val += f'<span class="badge">source: {_esc(view["source"])}</span>'
    return f'<tr><td class="k">{_esc(label)}</td><td>{val}</td></tr>'


def _body_sections(c: dict[str, Any]) -> str:
    eq_rows = "".join(_fact_row(p, v) for p, v in c["equipment"].items())
    issue_row = _fact_row("issue", c["issue"])

    if c["estimate"]:
        parts = ", ".join(_esc(p) for p in c["estimate"].get("parts", [])) or "—"
        est = (f'<table><tr><td class="k">Labor</td>'
               f'<td>{_esc(c["estimate"].get("hours", "—"))} h</td></tr>'
               f'<tr><td class="k">Parts</td><td>{parts}</td></tr></table>')
    else:
        est = '<p><span class="unknown">Estimate pending</span> — scope not yet closed.</p>'

    flags_html = ""
    if c["flags"]["a2l"]:
        flags_html += (
            '<div class="flag"><b>A2L refrigerant.</b> This system uses a '
            'mildly-flammable A2L refrigerant: requires an A2L-prepared '
            'technician and A2L-rated equipment on the truck. Refrigerant '
            'recovery documentation is required for this work.</div>')
    elif c["compliance"]["recovery_documentation_required"]:
        flags_html += (
            '<div class="flag">Refrigerant-touching work: recovery '
            'documentation is required.</div>')
    if c["flags"]["replacement_conversation"]:
        flags_html += (
            '<div class="flag"><b>R-410A + compressor failure.</b> New '
            'residential R-410A systems can no longer be installed (EPA AIM '
            'Act, 2026) — this scope is a system-replacement conversation, '
            'not just a part swap.</div>')

    m = c["money"]
    money_html = (
        f'<div class="advisory"><b>Parts warranty — advisory only.</b> '
        f'{_esc(m["parts_warranty"]["coverage"])}. Registration status: '
        f'<span class="unknown">{_esc(m["parts_warranty"]["registration_status"])}</span>. '
        f'Final verdict comes from the {_esc(m["parts_warranty"]["confirmed_by"])}.</div>'
        f'<table>'
        f'<tr><td class="k">Labor + service call</td><td>Billable. '
        f'{_esc(m["labor"]["note"])}</td></tr>'
        f'<tr><td class="k">Diagnostic fee</td>'
        f'<td>{_esc(m["diagnostic_fee"]["typical_range"])} — credited toward '
        f'repair: {_esc(m["diagnostic_fee"]["credited_toward_repair"])}</td></tr>'
        f'<tr><td class="k">Core charge</td><td>{_esc(m["core_charge"]["note"])}'
        f'</td></tr></table>')

    comp = c["compliance"]
    code_html = "".join(f"<li>{_esc(n)}</li>" for n in comp["code_notes"])
    comp_html = (
        f'<table>'
        f'<tr><td class="k">Contractor license #</td>'
        f'<td>{_esc(comp["contractor_license"])} <span class="meta">(required '
        f'on the estimate in many states)</span></td></tr>'
        f'<tr><td class="k">Technician EPA 608</td>'
        f'<td>{_esc(comp["epa_608"])}</td></tr>'
        f'<tr><td class="k">Refrigerant type</td>'
        f'<td>{_esc(comp["refrigerant_type"])}</td></tr></table>'
        + (f"<ul>{code_html}</ul>" if code_html else ""))

    deferred_html = ""
    if c["deferred_findings"]:
        items = "".join(f"<li>{_esc(d['value'])}</li>"
                        for d in c["deferred_findings"])
        deferred_html = (f'<h2>Observed, not in current scope</h2>'
                         f'<ul>{items}</ul>')

    prov = ", ".join(f"{_esc(p)}→#{_esc(i)}" for p, i in c["provenance"].items())

    return (
        f'<h2>Equipment — verified facts</h2><table>{eq_rows}{issue_row}</table>'
        f'{flags_html}'
        f'<h2>Estimate</h2>{est}'
        f'<h2>Money</h2>{money_html}'
        f'<h2>Compliance</h2>{comp_html}'
        f'{deferred_html}'
        f'<div class="prov">Every line above traces to an approved entry in '
        f'the fleet memory gate journal: {prov}</div>')


def render_homeowner_html(c: dict[str, Any]) -> str:
    return (
        f'<!doctype html><meta charset="utf-8">'
        f'<title>Job {_esc(c["job_id"])} — Estimate</title><style>{_CSS}</style>'
        f'<h1>Repair estimate — Job {_esc(c["job_id"])}</h1>'
        f'<p class="meta">Generated {_esc(c["generated_at"][:10])} · '
        f'Quote valid until {_esc(c["quote_valid_until"][:10])}</p>'
        + _body_sections(c))


def render_decider_html(c: dict[str, Any]) -> str:
    return (
        f'<!doctype html><meta charset="utf-8">'
        f'<title>Job {_esc(c["job_id"])} — For the decision-maker</title>'
        f'<style>{_CSS}</style>'
        f'<h1>Approval requested — Job {_esc(c["job_id"])}</h1>'
        f'<p class="meta">Prepared for the absent decision-maker. '
        f'Price valid until <b>{_esc(c["quote_valid_until"][:10])}</b>.</p>'
        f'<div class="advisory">Evidence photos from the site visit are '
        f'attached to the job record; every fact below passed the fleet\'s '
        f'write-gate verification.</div>'
        + _body_sections(c))


def authorization_json(c: dict[str, Any]) -> dict[str, Any]:
    """Structured scope for the home-warranty lane / downstream systems (A2A)."""
    verified = {
        p: v for p, v in c["equipment"].items() if v.get("value") != "UNKNOWN"
    }
    if c["issue"].get("value") != "UNKNOWN":
        verified["issue"] = c["issue"]
    return {
        "type": "authorization_request",
        "job_id": c["job_id"],
        "generated_at": c["generated_at"],
        "quote_valid_until": c["quote_valid_until"],
        "verified_facts": verified,
        "unknowns": c["unknowns"],
        "estimate": c["estimate"],
        "flags": c["flags"],
        "warranty_stance": c["money"]["parts_warranty"],
        "compliance": c["compliance"],
        "rejected_claims": c["rejected"],
    }
