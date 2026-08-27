"""Fixture server for walking the office seat without the fleet or Postgres.

The real endpoints live in `dashboard/main.py` (Task 4) and derive everything
from `memory_facts` + `gate_journal`. This stub answers the same six URLs with
hand-built payloads in exactly the shapes Task 3/4 specify, so the front-end
can be click-tested before the API lane lands. Facts, verifier reasons, gate
entry ids and timestamps are copied from a real run
(`docs/design-variants-2026-08-26/state-snapshot.json`); addresses, client and
technician names are the sample workspace agreed in the spec.

    "<repo>/.venv/bin/python" scripts/dev_stub_office.py     # http://localhost:8081

The demo endpoints mimic the guarded live drive: `POST /api/demo/run` starts a
clock, `/api/demo/status` walks running -> pushback -> done over ~6 s, and once
it is done the Maple fixture grows one visit and one rejected open question so
the re-render path is exercised for real.
"""
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parents[1] / "dashboard" / "static"
MODEL = "gemini-3.7-flash"

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC), name="static")

demo = {"job_id": None, "status": "idle", "started_at": None, "reply": "", "error": "",
        "gate_base": 140}


def _done() -> bool:
    return demo["status"] == "done"


# --------------------------------------------------------------------------
# properties
# --------------------------------------------------------------------------
LAKESHORE = {
    "id": "1187-lakeshore-dr-orlando-fl-32803", "address": "1187 Lakeshore Dr",
    "city": "Orlando FL 32803", "client": "Dana Whitfield", "technician": "Alicia Reyes",
    "last_visit": "2026-08-21",
    "equipment_summary": "Bradford White RE340S6 · 2012 · 40 Gallons",
    "state": "calm", "open_questions": 0, "jobs": ["J-971", "J-970"],
}
MAPLE = {
    "id": "214-maple-ct-orlando-fl-32806", "address": "214 Maple Ct",
    "city": "Orlando FL 32806", "client": "Ray Okafor", "technician": "Alicia Reyes",
    "last_visit": "2026-08-26",
    "equipment_summary": "Rheem 82V40-2 · 05/2004 · 40 Gallons",
    "state": "needs_confirmation", "open_questions": 1, "jobs": ["J-DEMO-134922"],
}
FERNCREEK = {
    "id": "902-ferncreek-ave-orlando-fl-32804", "address": "902 Ferncreek Ave",
    "city": "Orlando FL 32804", "client": "Priya Raman", "technician": "Miguel Torres",
    "last_visit": "2026-08-25",
    "equipment_summary": "Goodman GMVC80 · Unknown · Unknown",
    "state": "unknowns", "open_questions": 2, "jobs": ["J-F1"],
}


def _properties():
    m = dict(MAPLE)
    if _done():
        m["open_questions"] = 2
        m["last_visit"] = time.strftime("%Y-%m-%d")
    return [m, LAKESHORE, FERNCREEK]


def chip(value, source, agent, ts, gate, predicate=None, status="known"):
    return {"value": value, "source": source, "agent": agent, "ts": ts,
            "gate_entry_id": gate, "status": status, "predicate": predicate}


MAPLE_DETAIL = {
    "property": MAPLE,
    "record_as_of": "2026-08-26T13:50:10.499120+00:00",
    "briefing": [
        {"text": "Electric water heater Rheem 82V40-2, 40 Gallons, in the garage — manufacture date 05/2004.",
         "source": "nameplate photo", "agent": "foreman", "ts": "2026-08-26T13:49:31.784397+00:00",
         "gate_entry_id": 104, "job_id": "J-DEMO-134922", "predicate": "manufacture_date"},
        {"text": "Visit 2026-08-26 (Alicia Reyes): No hot water since yesterday; breaker fine, tank warm at top only.",
         "source": "technician voice", "agent": "foreman", "ts": "2026-08-26T13:49:32.357640+00:00",
         "gate_entry_id": 105, "job_id": "J-DEMO-134922", "predicate": "issue"},
        {"text": "Serial number RH 0504B01826 is on record, so warranty can be settled by serial rather than by memory.",
         "source": "nameplate photo", "agent": "foreman", "ts": "2026-08-26T13:49:31.994543+00:00",
         "gate_entry_id": 103, "job_id": "J-DEMO-134922", "predicate": "serial_number"},
        {"text": "Estimate: 2 h · lower heating element, thermostat.",
         "source": "estimator", "agent": "estimator", "ts": "2026-08-26T13:49:52.488948+00:00",
         "gate_entry_id": 107, "job_id": "J-DEMO-134922", "predicate": "estimate"},
        {"text": "Refused: manufacture_date = 2022 — The proposed manufacture date contradicts the existing recorded manufacture date.",
         "source": "homeowner stated", "agent": "estimator", "ts": "2026-08-26T13:50:10.499120+00:00",
         "gate_entry_id": 108, "job_id": "J-DEMO-134922", "predicate": "manufacture_date"},
    ],
    "open_questions": [
        {"kind": "rejected", "job_id": "J-DEMO-134922", "predicate": "manufacture_date",
         "proposed": "2022",
         "reason": "The proposed manufacture date contradicts the existing recorded manufacture date.",
         "contradicts": {"value": "05/2004", "gate_entry_id": 104,
                         "decided_at": "2026-08-26T13:49:31.784397+00:00"},
         "gate_entry_id": 108, "ts": "2026-08-26T13:50:10.499120+00:00",
         "proposed_by": "estimator", "verifier_model": MODEL},
    ],
    "auto_passed": 11,
    "equipment": [
        {"model": "Rheem 82V40-2", "type": "Electric water heater", "status": "installed",
         "fields": {
             "equipment_model": chip("Rheem 82V40-2", "nameplate photo", "foreman",
                                     "2026-08-26T13:49:31.577205+00:00", 102),
             "serial_number": chip("RH 0504B01826", "nameplate photo", "foreman",
                                   "2026-08-26T13:49:31.994543+00:00", 103),
             "manufacture_date": chip("05/2004", "nameplate photo", "foreman",
                                      "2026-08-26T13:49:31.784397+00:00", 104),
             "capacity": chip("40 Gallons", "nameplate photo", "foreman",
                              "2026-08-26T13:49:34.274450+00:00", 106),
             "refrigerant": chip(None, "Resistive appliance — no refrigerant circuit", "foreman",
                                 "2026-08-26T13:49:34.274450+00:00", None, status="unknown"),
         }},
    ],
    "deferred": [],
    "visits": [
        {"job_id": "J-DEMO-134922", "date": "2026-08-26", "technician": "Alicia Reyes",
         "issue": "No hot water since yesterday; breaker fine, tank warm at top only",
         "estimate": "2 h · lower heating element, thermostat",
         "state": "needs_confirmation", "open": 1, "doc_url": "/doc/J-DEMO-134922"},
    ],
    "documents": [
        {"kind": "homeowner", "job_id": "J-DEMO-134922", "url": "/doc/J-DEMO-134922"},
        {"kind": "decider", "job_id": "J-DEMO-134922", "url": "/doc/J-DEMO-134922?mode=decider"},
        {"kind": "authorization", "job_id": "J-DEMO-134922", "url": "/api/closeout/J-DEMO-134922"},
    ],
}

LAKESHORE_DETAIL = {
    "property": LAKESHORE,
    "record_as_of": "2026-08-21T09:33:04.113000+00:00",
    "briefing": [
        {"text": "Water heater Bradford White RE340S6, 40 Gallons, in the garage — manufacture date 2012.",
         "source": "nameplate photo", "agent": "foreman", "ts": "2026-08-21T09:33:04.113000+00:00",
         "gate_entry_id": 88, "job_id": "J-971", "predicate": "manufacture_date"},
        {"text": "Visit 2026-08-21 (Alicia Reyes): dripping at the base, drain valve looks corroded.",
         "source": "technician voice", "agent": "foreman", "ts": "2026-08-21T09:31:12.900000+00:00",
         "gate_entry_id": 86, "job_id": "J-971", "predicate": "issue"},
        {"text": "Estimate: 2 h · drain valve.",
         "source": "estimator", "agent": "estimator", "ts": "2026-08-21T09:35:41.220000+00:00",
         "gate_entry_id": 90, "job_id": "J-971", "predicate": "estimate"},
        {"text": "Visit 2026-06-18 (Miguel Torres): leaking near the drain valve, tank itself looks dry.",
         "source": "technician voice", "agent": "foreman", "ts": "2026-06-18T10:24:03.500000+00:00",
         "gate_entry_id": 74, "job_id": "J-970", "predicate": "issue"},
        {"text": "Noticed, not repaired: no expansion tank on a closed system.",
         "source": "technician voice", "agent": "foreman", "ts": "2026-06-18T11:02:47.310000+00:00",
         "gate_entry_id": 77, "job_id": "J-970", "predicate": "deferred_expansion_tank"},
    ],
    "open_questions": [],
    "auto_passed": 9,
    "equipment": [
        {"model": "Bradford White RE340S6", "type": "Water heater", "status": "installed",
         "fields": {
             "equipment_model": chip("Bradford White RE340S6", "nameplate photo", "foreman",
                                     "2026-08-21T09:33:04.113000+00:00", 87),
             "serial_number": chip("BW 1204T99031", "nameplate photo", "foreman",
                                   "2026-08-21T09:33:19.400000+00:00", 89),
             "manufacture_date": chip("2012", "nameplate photo", "foreman",
                                      "2026-08-21T09:33:04.113000+00:00", 88),
             "capacity": chip("40 Gallons", "nameplate photo", "foreman",
                              "2026-08-21T09:33:22.010000+00:00", 91),
         }},
    ],
    "deferred": [
        {"text": "No expansion tank on a closed system — noted, not repaired.",
         "technician": "Miguel Torres", "ts": "2026-06-18T11:02:47.310000+00:00",
         "job_id": "J-970", "gate_entry_id": 77},
    ],
    "visits": [
        {"job_id": "J-971", "date": "2026-08-21", "technician": "Alicia Reyes",
         "issue": "dripping at the base, drain valve looks corroded",
         "estimate": "2 h · drain valve", "state": "done", "open": 0,
         "doc_url": "/doc/J-971"},
        {"job_id": "J-970", "date": "2026-06-18", "technician": "Miguel Torres",
         "issue": "leaking near the drain valve, tank itself looks dry",
         "estimate": "2 h · drain valve", "state": "done", "open": 0,
         "doc_url": "/doc/J-970"},
    ],
    "documents": [
        {"kind": "homeowner", "job_id": "J-971", "url": "/doc/J-971"},
        {"kind": "decider", "job_id": "J-971", "url": "/doc/J-971?mode=decider"},
        {"kind": "authorization", "job_id": "J-971", "url": "/api/closeout/J-971"},
    ],
}

FERNCREEK_DETAIL = {
    "property": FERNCREEK,
    "record_as_of": "2026-08-25T16:12:44.800000+00:00",
    "briefing": [
        {"text": "Gas furnace Goodman GMVC80 in the hall closet.",
         "source": "nameplate photo", "agent": "foreman", "ts": "2026-08-25T16:12:44.800000+00:00",
         "gate_entry_id": 121, "job_id": "J-F1", "predicate": "equipment_model"},
        {"text": "Visit 2026-08-25 (Miguel Torres): furnace short-cycles, blower runs but no heat.",
         "source": "technician voice", "agent": "foreman", "ts": "2026-08-25T16:13:02.140000+00:00",
         "gate_entry_id": 123, "job_id": "J-F1", "predicate": "issue"},
        {"text": "Serial number unknown — plate unreadable.",
         "source": "plate unreadable", "agent": "foreman", "ts": "2026-08-25T16:12:51.660000+00:00",
         "gate_entry_id": 122, "job_id": "J-F1", "predicate": "serial_number"},
        {"text": "Manufacture date unknown — plate unreadable.",
         "source": "plate unreadable", "agent": "foreman", "ts": "2026-08-25T16:12:53.020000+00:00",
         "gate_entry_id": 124, "job_id": "J-F1", "predicate": "manufacture_date"},
    ],
    "open_questions": [
        {"kind": "unknown", "job_id": "J-F1", "predicate": "serial_number",
         "reason": "plate unreadable", "gate_entry_id": 122,
         "ts": "2026-08-25T16:12:51.660000+00:00"},
        {"kind": "unknown", "job_id": "J-F1", "predicate": "manufacture_date",
         "reason": "plate unreadable", "gate_entry_id": 124,
         "ts": "2026-08-25T16:12:53.020000+00:00"},
    ],
    "auto_passed": 6,
    "equipment": [
        {"model": "Goodman GMVC80", "type": "Gas furnace", "status": "installed",
         "fields": {
             "equipment_model": chip("Goodman GMVC80", "nameplate photo", "foreman",
                                     "2026-08-25T16:12:44.800000+00:00", 121),
             "serial_number": chip(None, "plate unreadable", "foreman",
                                   "2026-08-25T16:12:51.660000+00:00", 122, status="unknown"),
             "manufacture_date": chip(None, "plate unreadable", "foreman",
                                      "2026-08-25T16:12:53.020000+00:00", 124, status="unknown"),
             "capacity": chip(None, "not on any captured frame", "foreman",
                              "2026-08-25T16:12:55.400000+00:00", None, status="unknown"),
         }},
    ],
    "deferred": [],
    "visits": [
        {"job_id": "J-F1", "date": "2026-08-25", "technician": "Miguel Torres",
         "issue": "furnace short-cycles, blower runs but no heat",
         "estimate": "", "state": "in_progress", "open": 2, "doc_url": ""},
    ],
    "documents": [],
}

DETAILS = {p["property"]["id"]: p for p in (MAPLE_DETAIL, LAKESHORE_DETAIL, FERNCREEK_DETAIL)}


@app.get("/api/properties")
async def api_properties():
    props = _properties()
    counters = {"approved": 101 + (4 if _done() else 0),
                "rejected": 3 + (1 if _done() else 0),
                "total": 104 + (5 if _done() else 0)}
    return JSONResponse({"properties": props, "counters": counters, "no_property_jobs": 7})


@app.get("/api/property/{prop_id}")
async def api_property(prop_id: str):
    d = DETAILS.get(prop_id)
    if d is None:
        return JSONResponse({"error": "unknown property"}, status_code=404)
    if prop_id != MAPLE["id"] or not _done():
        return JSONResponse(d)

    # the live run landed: one more visit, one more refusal on the record
    job = demo["job_id"] or "J-DEMO-000000"
    today = time.strftime("%Y-%m-%d")
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    grown = {**d, "property": _properties()[0], "record_as_of": now, "auto_passed": 15}
    grown["briefing"] = [
        {"text": f"Visit {today} (Alicia Reyes): No hot water since yesterday; breaker fine, tank warm at top only.",
         "source": "technician voice", "agent": "foreman", "ts": now,
         "gate_entry_id": demo["gate_base"] + 1, "job_id": job, "predicate": "issue"},
    ] + d["briefing"]
    grown["open_questions"] = [
        {"kind": "rejected", "job_id": job, "predicate": "manufacture_date", "proposed": "2022",
         "reason": "Proposal contradicts existing manufacture date.",
         "contradicts": {"value": "05/2004", "gate_entry_id": 104,
                         "decided_at": "2026-08-26T13:49:31.784397+00:00"},
         "gate_entry_id": demo["gate_base"] + 8, "ts": now, "proposed_by": "estimator",
         "verifier_model": MODEL},
    ] + d["open_questions"]
    grown["visits"] = [
        {"job_id": job, "date": today, "technician": "Alicia Reyes",
         "issue": "No hot water since yesterday; breaker fine, tank warm at top only",
         "estimate": "2 h · lower heating element, thermostat",
         "state": "needs_confirmation", "open": 1, "doc_url": f"/doc/{job}"},
    ] + d["visits"]
    grown["documents"] = [
        {"kind": "homeowner", "job_id": job, "url": f"/doc/{job}"},
        {"kind": "decider", "job_id": job, "url": f"/doc/{job}?mode=decider"},
        {"kind": "authorization", "job_id": job, "url": f"/api/closeout/{job}"},
    ] + d["documents"]
    return JSONResponse(grown)


@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    return JSONResponse({
        "job_id": job_id,
        "property": {"id": MAPLE["id"], "address": MAPLE["address"]},
        "facts": {
            "equipment": [
                {"predicate": "equipment_model", "label": "Model", "value": "Rheem 82V40-2",
                 "source": "nameplate photo", "agent": "foreman",
                 "ts": "2026-08-26T13:49:31.577205+00:00", "gate_entry_id": 102, "status": "known"},
                {"predicate": "serial_number", "label": "Serial number", "value": "RH 0504B01826",
                 "source": "nameplate photo", "agent": "foreman",
                 "ts": "2026-08-26T13:49:31.994543+00:00", "gate_entry_id": 103, "status": "known"},
                {"predicate": "manufacture_date", "label": "Manufacture date", "value": "05/2004",
                 "source": "nameplate photo", "agent": "foreman",
                 "ts": "2026-08-26T13:49:31.784397+00:00", "gate_entry_id": 104, "status": "known"},
                {"predicate": "capacity", "label": "Capacity", "value": "40 Gallons",
                 "source": "nameplate photo", "agent": "foreman",
                 "ts": "2026-08-26T13:49:34.274450+00:00", "gate_entry_id": 106, "status": "known"},
                {"predicate": "refrigerant", "label": "Refrigerant", "value": None,
                 "source": "Resistive appliance — no refrigerant circuit", "agent": "foreman",
                 "ts": "2026-08-26T13:49:34.274450+00:00", "gate_entry_id": None, "status": "unknown"},
            ],
            "money": [
                {"predicate": "estimate", "label": "Estimate", "value": "2 h · lower heating element, thermostat",
                 "source": "estimator", "agent": "estimator",
                 "ts": "2026-08-26T13:49:52.488948+00:00", "gate_entry_id": 107, "status": "known"},
                {"predicate": "parts_warranty", "label": "Parts warranty", "value": None,
                 "source": "registration status unknown — the supply house decides by serial",
                 "agent": "closer", "ts": "2026-08-26T13:49:58.000000+00:00",
                 "gate_entry_id": None, "status": "unknown"},
            ],
            "deferred": [],
            "other": [
                {"predicate": "property", "label": "Property", "value": "214 Maple Ct, Orlando FL 32806",
                 "source": "intake", "agent": "foreman", "ts": "2026-08-26T13:49:20.000000+00:00",
                 "gate_entry_id": 99, "status": "known"},
                {"predicate": "technician", "label": "Technician", "value": "Alicia Reyes",
                 "source": "intake", "agent": "foreman", "ts": "2026-08-26T13:49:20.000000+00:00",
                 "gate_entry_id": 100, "status": "known"},
                {"predicate": "issue", "label": "Issue",
                 "value": "No hot water since yesterday; breaker fine, tank warm at top only",
                 "source": "technician voice", "agent": "foreman",
                 "ts": "2026-08-26T13:49:32.357640+00:00", "gate_entry_id": 105, "status": "known"},
            ],
        },
        "journal": [
            {"id": 108, "agent": "estimator", "verdict": "rejected", "subject": f"job:{job_id}",
             "predicate": "manufacture_date", "value": "2022",
             "reason": "The proposed manufacture date contradicts the existing recorded manufacture date.",
             "model": MODEL, "decided_at": "2026-08-26T13:50:10.499120+00:00"},
            {"id": 107, "agent": "estimator", "verdict": "approved", "subject": f"job:{job_id}",
             "predicate": "estimate",
             "value": '{"job": "J-DEMO-134922", "hours": 2, "parts": ["lower heating element", "thermostat"]}',
             "reason": "The proposed estimate is well-formed, plausible, and does not conflict with existing facts.",
             "model": MODEL, "decided_at": "2026-08-26T13:49:52.488948+00:00"},
            {"id": 104, "agent": "foreman", "verdict": "approved", "subject": f"job:{job_id}",
             "predicate": "manufacture_date", "value": "05/2004",
             "reason": "The proposed manufacture date is valid and does not contradict any existing facts.",
             "model": MODEL, "decided_at": "2026-08-26T13:49:31.784397+00:00"},
        ],
        "closeout": None,
        "similar": [
            {"job_id": "J-VRTX1", "predicate": "issue", "value": "water heater leaking from the bottom",
             "score": 0.71},
            {"job_id": "J-970", "predicate": "issue", "value": "leaking near the drain valve",
             "score": 0.66},
        ],
    })


@app.get("/api/state")
async def api_state():
    journal = [
        {"id": 108, "agent": "estimator", "verdict": "rejected", "subject": "job:J-DEMO-134922",
         "predicate": "manufacture_date", "value": "2022",
         "reason": "The proposed manufacture date contradicts the existing recorded manufacture date.",
         "model": MODEL, "decided_at": "2026-08-26T13:50:10.499120+00:00"},
        {"id": 107, "agent": "estimator", "verdict": "approved", "subject": "job:J-DEMO-134922",
         "predicate": "estimate",
         "value": '{"job": "J-DEMO-134922", "hours": 2, "parts": ["lower heating element", "thermostat"]}',
         "reason": "The proposed estimate is well-formed, plausible, and does not conflict with existing facts.",
         "model": MODEL, "decided_at": "2026-08-26T13:49:52.488948+00:00"},
        {"id": 106, "agent": "foreman", "verdict": "approved", "subject": "job:J-DEMO-134922",
         "predicate": "capacity", "value": "40 Gallons",
         "reason": "The proposed fact is well-formed, plausible, and does not contradict any existing facts.",
         "model": MODEL, "decided_at": "2026-08-26T13:49:34.274450+00:00"},
        {"id": 105, "agent": "foreman", "verdict": "approved", "subject": "job:J-DEMO-134922",
         "predicate": "issue", "value": "No hot water since yesterday; breaker fine, tank warm at top only",
         "reason": "Proposal is consistent and well-formed.",
         "model": MODEL, "decided_at": "2026-08-26T13:49:32.357640+00:00"},
        {"id": 104, "agent": "foreman", "verdict": "approved", "subject": "job:J-DEMO-134922",
         "predicate": "manufacture_date", "value": "05/2004",
         "reason": "The proposed manufacture date is valid and does not contradict any existing facts.",
         "model": MODEL, "decided_at": "2026-08-26T13:49:31.784397+00:00"},
        {"id": 103, "agent": "foreman", "verdict": "approved", "subject": "job:J-DEMO-134922",
         "predicate": "serial_number", "value": "RH 0504B01826",
         "reason": "Proposal is well-formed, plausible, and does not contradict any existing facts.",
         "model": MODEL, "decided_at": "2026-08-26T13:49:31.994543+00:00"},
        {"id": 122, "agent": "foreman", "verdict": "approved", "subject": "job:J-F1",
         "predicate": "serial_number", "value": "UNKNOWN",
         "reason": "Recording the unknown is correct; the plate is unreadable in the captured frame.",
         "model": MODEL, "decided_at": "2026-08-25T16:12:51.660000+00:00"},
        {"id": 90, "agent": "estimator", "verdict": "approved", "subject": "job:J-971",
         "predicate": "estimate", "value": '{"job": "J-971", "hours": 2, "parts": ["drain valve"]}',
         "reason": "The proposed estimate is plausible and consistent with the recorded issue.",
         "model": MODEL, "decided_at": "2026-08-21T09:35:41.220000+00:00"},
    ]
    jobs = [
        {"subject": "job:J-DEMO-134922", "facts": [
            {"predicate": "property", "value": "214 Maple Ct, Orlando FL 32806", "agent": "foreman"},
            {"predicate": "issue", "value": "No hot water since yesterday; breaker fine, tank warm at top only",
             "agent": "foreman"},
            {"predicate": "equipment_model", "value": "Rheem 82V40-2", "agent": "foreman"},
            {"predicate": "serial_number", "value": "RH 0504B01826", "agent": "foreman"},
        ]},
        {"subject": "job:J-971", "facts": [
            {"predicate": "property", "value": "1187 Lakeshore Dr, Orlando FL 32803", "agent": "foreman"},
            {"predicate": "issue", "value": "dripping at the base, drain valve looks corroded", "agent": "foreman"},
        ]},
        {"subject": "job:J-970", "facts": [
            {"predicate": "property", "value": "1187 Lakeshore Dr, Orlando FL 32803", "agent": "foreman"},
            {"predicate": "issue", "value": "leaking near the drain valve, tank itself looks dry", "agent": "foreman"},
        ]},
        {"subject": "job:J-F1", "facts": [
            {"predicate": "property", "value": "902 Ferncreek Ave, Orlando FL 32804", "agent": "foreman"},
            {"predicate": "issue", "value": "furnace short-cycles, blower runs but no heat", "agent": "foreman"},
            {"predicate": "serial_number", "value": "UNKNOWN", "agent": "foreman"},
        ]},
        {"subject": "job:J-VRTX1", "facts": [
            {"predicate": "issue", "value": "water heater leaking from the bottom", "agent": "foreman"},
        ]},
    ]
    return JSONResponse({
        "agents": [
            {"name": "closer", "version": "0.2", "description": "Closes a job into a verified client-facing document"},
            {"name": "estimator", "version": "0.2", "description": "Estimates repair scope and cost"},
            {"name": "foreman", "version": "0.2", "description": "Routes repair requests, records reported facts"},
        ],
        "journal": journal, "jobs": jobs, "activity": [],
        "counters": {"approved": 101, "rejected": 3, "total": 104},
    })


@app.post("/api/demo/run")
async def demo_run():
    if demo["status"] in ("running", "pushback"):
        return JSONResponse({"ok": False, "why": "a demo run is already in flight — watch the ledger"},
                            status_code=429)
    job_id = "J-DEMO-" + time.strftime("%H%M%S")
    demo.update(job_id=job_id, status="running", started_at=time.time(), reply="", error="",
                gate_base=demo["gate_base"] + 10)
    return {"ok": True, "job_id": job_id}


@app.get("/api/demo/status")
async def demo_status():
    started = demo["started_at"]
    if started:
        age = time.time() - started
        if demo["status"] in ("running", "pushback"):
            demo["status"] = "running" if age < 3 else ("pushback" if age < 6 else "done")
            if demo["status"] == "done":
                demo["reply"] = ("Recorded the visit at 214 Maple Ct and refused the 2022 "
                                 "manufacture date — the nameplate reading stands.")
    return {"job_id": demo["job_id"], "status": demo["status"], "reply": demo["reply"],
            "error": demo["error"], "elapsed": int(time.time() - started) if started else None}


@app.get("/")
async def index():
    return FileResponse(STATIC / "app" / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning")
