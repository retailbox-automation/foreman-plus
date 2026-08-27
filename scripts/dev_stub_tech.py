"""Local walkthrough stub for the technician seat (`/tech`).

Serves the real static files with FIXTURE JSON in the exact shapes of Tasks 3
and 5 of the UX/IA-B plan, so the three screens can be click-tested without the
fleet, Postgres or Cloud Run. Never used in production.

    "…/.venv/bin/python" scripts/dev_stub_tech.py     # http://localhost:8082/tech
"""
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "dashboard" / "static"
JOB_ID = "J-T-104512"
COOLDOWN_S = 30
TS = "2026-08-27T13:41:07+00:00"

app = FastAPI(title="tech seat dev stub")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

PROPERTIES = [
    {"id": "214-maple-ct-orlando-fl-32806", "address": "214 Maple Ct", "city": "Orlando FL 32806",
     "client": "Ray Okafor", "technician": "Alicia Reyes", "last_visit": "2026-08-26",
     "equipment_summary": "Rheem 82V40-2 · 05/2004 · 40 Gallons",
     "state": "needs_confirmation", "open_questions": 2, "jobs": ["J-DEMO-134922", "J-VRTX1"]},
    {"id": "1187-lakeshore-dr-orlando-fl-32806", "address": "1187 Lakeshore Dr",
     "city": "Orlando FL 32806", "client": "Dana Whitfield", "technician": "Miguel Torres",
     "last_visit": "2026-08-21", "equipment_summary": "Rheem XE40M06ST45U1 · 08/2019 · 40 Gallons",
     "state": "calm", "open_questions": 0, "jobs": ["J-971", "J-970"]},
    {"id": "902-ferncreek-ave-orlando-fl-32806", "address": "902 Ferncreek Ave",
     "city": "Orlando FL 32806", "client": "Priya Nandakumar", "technician": "Miguel Torres",
     "last_visit": "2026-08-19", "equipment_summary": "Goodman GSX140361 · 03/2016 · 3 Tons",
     "state": "unknowns", "open_questions": 1, "jobs": ["J-991"]},
]

REJECT_REASON = ("The proposed manufacture date contradicts the existing recorded "
                 "manufacture date")

DETAIL = {
    "214-maple-ct-orlando-fl-32806": {
        "property": PROPERTIES[0],
        "record_as_of": TS,
        "briefing": [
            {"text": "Electric water heater Rheem 82V40-2, 40 Gallons, in the garage — "
                     "manufacture date 05/2004.",
             "source": "nameplate photo", "agent": "foreman", "ts": TS, "gate_entry_id": 104,
             "job_id": "J-DEMO-134922", "predicate": "manufacture_date"},
            {"text": "Visit 2026-08-26 (Alicia Reyes): No hot water since yesterday; breaker fine, "
                     "tank warm at top only.",
             "source": "technician voice", "agent": "foreman", "ts": TS, "gate_entry_id": 105,
             "job_id": "J-DEMO-134922", "predicate": "issue"},
            {"text": "Estimate: 2 h · lower heating element, thermostat.",
             "source": "estimator", "agent": "estimator", "ts": TS, "gate_entry_id": 109,
             "job_id": "J-DEMO-134922", "predicate": "estimate"},
            {"text": "Serial number unknown — plate unreadable.",
             "source": "plate unreadable", "agent": "foreman", "ts": TS, "gate_entry_id": 106,
             "job_id": "J-DEMO-134922", "predicate": "serial_number"},
            {"text": "Refused: manufacture_date = 2022 — " + REJECT_REASON,
             "source": "homeowner statement", "agent": "estimator", "ts": TS,
             "gate_entry_id": 108, "job_id": "J-DEMO-134922", "predicate": "manufacture_date"},
        ],
        "open_questions": [
            {"kind": "rejected", "job_id": "J-DEMO-134922", "predicate": "manufacture_date",
             "proposed": "2022", "reason": REJECT_REASON,
             "contradicts": {"value": "05/2004", "gate_entry_id": 104, "decided_at": TS},
             "gate_entry_id": 108, "ts": TS, "proposed_by": "estimator"},
            {"kind": "unknown", "job_id": "J-DEMO-134922", "predicate": "serial_number",
             "reason": "plate unreadable", "gate_entry_id": 106, "ts": TS},
        ],
        "auto_passed": 11,
        "equipment": [],
        "deferred": [
            {"text": "Full replacement quoted and deferred by the homeowner.",
             "technician": "Miguel Torres", "ts": "2026-08-20T09:12:00+00:00",
             "job_id": "J-VRTX1", "gate_entry_id": 77},
        ],
        "visits": [],
        "documents": [],
    }
}
for p in PROPERTIES[1:]:
    DETAIL[p["id"]] = {"property": p, "record_as_of": TS, "briefing": [], "open_questions": [],
                       "auto_passed": 0, "equipment": [], "deferred": [], "visits": [],
                       "documents": []}

JOB = {
    "job_id": JOB_ID,
    "property": {"id": "214-maple-ct-orlando-fl-32806", "address": "214 Maple Ct"},
    "facts": {
        "equipment": [
            {"predicate": "equipment_model", "label": "Model", "value": "Rheem 82V40-2",
             "source": "nameplate photo", "agent": "foreman", "ts": TS,
             "gate_entry_id": 141, "status": "known"},
            {"predicate": "capacity", "label": "Capacity", "value": "40 Gallons",
             "source": "nameplate photo", "agent": "foreman", "ts": TS,
             "gate_entry_id": 142, "status": "known"},
            {"predicate": "serial_number", "label": "Serial number", "value": "UNKNOWN",
             "source": "plate unreadable", "agent": "foreman", "ts": TS,
             "gate_entry_id": 143, "status": "unknown"},
        ],
        "money": [
            {"predicate": "estimate", "label": "Estimate", "value": "2 h · lower heating element, thermostat",
             "source": "estimator", "agent": "estimator", "ts": TS,
             "gate_entry_id": 146, "status": "known"},
        ],
        "deferred": [],
        "other": [
            {"predicate": "issue", "label": "Issue",
             "value": "No hot water; tank warm at the top only",
             "source": "technician voice", "agent": "foreman", "ts": TS,
             "gate_entry_id": 144, "status": "known"},
            {"predicate": "technician", "label": "Technician", "value": "Alicia Reyes",
             "source": "intake", "agent": "foreman", "ts": TS,
             "gate_entry_id": 145, "status": "known"},
        ],
    },
    "journal": [
        {"id": 147, "proposed_by": "estimator", "verdict": "rejected",
         "reason": REJECT_REASON, "verifier_model": "gemini-3.7-flash",
         "decided_at": TS, "created_at": TS,
         "predicate": "manufacture_date", "proposed": "2022",
         "contradicts": {"value": "05/2004", "gate_entry_id": 104, "decided_at": TS},
         "proposal": {"subject": f"job:{JOB_ID}", "predicate": "manufacture_date",
                      "object": {"value": "2022", "source": "homeowner statement"}}},
        {"id": 146, "proposed_by": "estimator", "verdict": "approved", "reason": "ok",
         "verifier_model": "gemini-3.7-flash", "decided_at": TS, "created_at": TS,
         "proposal": {"subject": f"job:{JOB_ID}", "predicate": "estimate",
                      "object": {"value": "2 h"}}},
    ],
    "closeout": None,
    "similar": [],
}

state = {"last_start": 0.0, "started_at": 0.0}


@app.get("/tech")
def tech():
    return FileResponse(STATIC / "tech" / "index.html")


@app.get("/api/properties")
def properties():
    return {"properties": PROPERTIES,
            "counters": {"approved": 46, "rejected": 3, "total": 49},
            "no_property_jobs": 1}


@app.get("/api/property/{prop_id}")
def property_detail(prop_id: str):
    d = DETAIL.get(prop_id)
    if not d:
        return JSONResponse({"error": "unknown property"}, status_code=404)
    return d


@app.post("/api/intake")
async def intake(property: str = Form(...), technician: str = Form(...),
                 client: str = Form(""), notes: str = Form(""),
                 photo: UploadFile = File(...), audio: UploadFile | None = File(None)):
    now = time.time()
    left = int(COOLDOWN_S - (now - state["last_start"]))
    if left > 0:
        return JSONResponse({"ok": False, "why": f"cooldown — try again in {left}s"},
                            status_code=429)
    await photo.read()
    if audio is not None:
        await audio.read()
    state["last_start"] = now
    state["started_at"] = now
    print(f"[stub] intake {JOB_ID}: {property} · {technician} · notes={notes!r} "
          f"· photo={photo.content_type} · audio={audio.content_type if audio else None}")
    return {"ok": True, "job_id": JOB_ID}


@app.get("/api/intake/status")
def intake_status(job_id: str):
    if job_id != JOB_ID or not state["started_at"]:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    elapsed = time.time() - state["started_at"]
    facts = 0 if elapsed < 2.5 else (2 if elapsed < 5.5 else 5)
    status = "done" if elapsed >= 8 else "running"
    return {"job_id": JOB_ID, "status": status, "elapsed": int(elapsed),
            "reply": "Recorded 5 facts; the 2022 date the homeowner gave was refused."
                     if status == "done" else "",
            "error": "", "facts": facts, "property": "214 Maple Ct, Orlando FL 32806"}


@app.get("/api/job/{job_id}")
def job(job_id: str):
    if job_id != JOB_ID:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return JOB


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8082, log_level="warning")
