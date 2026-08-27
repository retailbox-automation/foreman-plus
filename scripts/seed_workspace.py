"""Seed the Foreman+ sample workspace through the real fleet.

Three sample properties, seven visits (two properties get repeat visits /
housekeeping addresses on legacy jobs), driven entirely through the deployed
fleet's public REST contract — same shape as glass_bridge/src/job.ts's
buildRunPayload() and dashboard/main.py's _drive_fleet(). Nothing is ever
SQL-inserted; every fact lands through record_fact + the write-gate, same as
a technician's real intake.

Usage:
  .venv/bin/python scripts/seed_workspace.py --dry-run
  .venv/bin/python scripts/seed_workspace.py --run \\
      [--only JOB_ID] [--fleet-url URL] [--db-url postgresql://...]

--dry-run prints the plan (7 visits) and exits — no network, no DB, safe to
run from a laptop with nothing configured.

--run talks to the LIVE fleet (Vertex-billed) and needs:
  - GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account key with
    run.invoker on the fleet's Cloud Run service (see README.md's deploy
    section) — used for the ID token, same as dashboard/main.py::_id_token.
  - --db-url or $FOREMAN_DB_URL — a Postgres DSN asyncpg can use directly.
    Against Cloud SQL this means a cloud-sql-proxy tunnel is already running
    (see scripts/backfill_embeddings.py's docstring) and --db-url points at
    that local port, e.g. postgresql://postgres:PW@localhost:5433/foreman.

Idempotent: a visit whose job already has a current `property` fact is
skipped (never double-seeded). Exits non-zero if any visit that actually ran
ends without a `property` fact recorded.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

FLEET_URL_DEFAULT = "https://foreman-hello-112293816563.us-central1.run.app"
RUN_TIMEOUT_S = 600   # one visit can take minutes when Vertex throttles the verifier
SLEEP_BETWEEN_VISITS_S = 5

# (a) 1187 Lakeshore Dr — two visits, two technicians, one deferred finding
# (b) 214 Maple Ct — existing real job gets its address (dispute already on
#     record on J-DEMO-134922); housekeeping only, no re-recorded equipment
# (c) 902 Ferncreek Ave — worn plate: model readable, serial not
# legacy jobs (J-970/J-971/J-VRTX1) get an address so they join the workspace
VISITS: list[dict[str, Any]] = [
    {"job_id": "J-LAKE-1", "property": "1187 Lakeshore Dr, Orlando FL 32803", "technician": "Miguel Torres",
     "client": "Dana Whitfield", "photo": "scripts/seed_assets/lakeshore-bradford-white.jpg",
     "notes": ["Electric water heater in the utility closet, leaking near the drain valve.",
               "Noticed: no expansion tank on this closed system — not repaired today, homeowner informed."],
     "followups": []},
    {"job_id": "J-LAKE-2", "property": "1187 Lakeshore Dr, Orlando FL 32803", "technician": "Alicia Reyes",
     "client": "Dana Whitfield", "photo": "scripts/seed_assets/lakeshore-bradford-white.jpg",
     "notes": ["Callback on the same tank: dripping at the base, drain valve looks corroded.",
               "Before you estimate, check what the fleet already knows about this unit."],
     "followups": []},
    {"job_id": "J-DEMO-134922", "property": "214 Maple Ct, Orlando FL 32806", "technician": "Alicia Reyes",
     "client": "Ray Okafor", "photo": None,
     "notes": ["Housekeeping: this job is at 214 Maple Ct, Orlando FL 32806, technician Alicia Reyes, client Ray Okafor. Record property, technician and client only; do not re-record equipment facts and do not hand off to the estimator."],
     "followups": []},
    {"job_id": "J-FERN-1", "property": "902 Ferncreek Ave, Orlando FL 32806", "technician": "Miguel Torres",
     "client": "Priya Raman", "photo": "scripts/seed_assets/ferncreek-lg-dryer-worn.jpg",
     "notes": ["Electric dryer, no heat at all, drum turns.",
               "The plate is worn — I can make out the model but not the serial number."],
     "followups": []},
    {"job_id": "J-970", "property": "1187 Lakeshore Dr, Orlando FL 32803", "technician": "Miguel Torres", "client": "Dana Whitfield", "photo": None,
     "notes": ["Housekeeping: this job is at 1187 Lakeshore Dr, Orlando FL 32803, technician Miguel Torres, client Dana Whitfield. Record property, technician and client only; do not re-record equipment facts and do not hand off to the estimator."], "followups": []},
    {"job_id": "J-971", "property": "1187 Lakeshore Dr, Orlando FL 32803", "technician": "Alicia Reyes", "client": "Dana Whitfield", "photo": None,
     "notes": ["Housekeeping: this job is at 1187 Lakeshore Dr, Orlando FL 32803, technician Alicia Reyes, client Dana Whitfield. Record property, technician and client only; do not re-record equipment facts and do not hand off to the estimator."], "followups": []},
    {"job_id": "J-VRTX1", "property": "214 Maple Ct, Orlando FL 32806", "technician": "Miguel Torres", "client": "Ray Okafor", "photo": None,
     "notes": ["Housekeeping: this job is at 214 Maple Ct, Orlando FL 32806, technician Miguel Torres, client Ray Okafor. Record property, technician and client only; do not re-record equipment facts and do not hand off to the estimator."], "followups": []},
]


def build_plan() -> list[dict[str, Any]]:
    """The seed plan: 7 visits across the 3 sample properties. Pure/no I/O."""
    return [dict(v) for v in VISITS]


def _seed_intake_text(visit: dict[str, Any]) -> str:
    """Task-5-style intake wording for a visit WITH a photo, adapted for the
    seeding run (list of notes, not one typed-notes string; "a seeding run"
    instead of "the technician's phone")."""
    job_id = visit["job_id"]
    prop = visit["property"]
    tech = visit["technician"]
    client = visit.get("client") or ""
    notes = visit.get("notes") or []
    bullets = "\n".join(f"- {n}" for n in notes)
    return (
        f"Field intake for job {job_id} at {prop}. Technician: {tech}. "
        + (f"Client: {client}. " if client else "")
        + "Submitted from a seeding run. The photo is the equipment nameplate "
        "or the equipment itself. "
        + (f"Technician's spoken notes:\n{bullets}\n" if bullets else "")
        + "Record the property, technician and client as facts. Record every nameplate "
        "field you can read with source \"nameplate photo\"; if a field is unreadable, "
        "record it as UNKNOWN with source \"plate unreadable\". Record the reported issue "
        "and observations with source \"technician voice\"; anything attributed to the "
        "homeowner with source \"homeowner statement\". Then hand off to the estimator "
        "for a scope estimate. End with a ONE-SENTENCE summary for the technician."
    )


def run_payload(visit: dict[str, Any], photo_bytes: bytes | None, mime: str | None) -> dict[str, Any]:
    """Build the RunAgentRequest body for one visit's opening turn.

    A visit WITH a photo gets the wrapped Task-5-style intake text plus an
    inlineData part for the photo. A housekeeping visit (photo is None) sends
    its single note VERBATIM — no wrapper, no estimator handoff requested.
    """
    if visit["photo"]:
        parts: list[dict[str, Any]] = [{"text": _seed_intake_text(visit)}]
        if photo_bytes:
            parts.append({"inlineData": {"mimeType": mime or "image/jpeg",
                                          "data": base64.b64encode(photo_bytes).decode()}})
    else:
        notes = visit.get("notes") or []
        parts = [{"text": "\n".join(notes)}]
    return {
        "app_name": "foreman_app",
        "user_id": "seed",
        "session_id": visit["job_id"],
        "new_message": {"role": "user", "parts": parts},
    }


def _followup_payload(job_id: str, text: str) -> dict[str, Any]:
    return {
        "app_name": "foreman_app",
        "user_id": "seed",
        "session_id": job_id,
        "new_message": {"role": "user", "parts": [{"text": text}]},
    }


def _print_plan(plan: list[dict[str, Any]]) -> None:
    print(f"{len(plan)} visit(s) planned:\n")
    for v in plan:
        photo = v["photo"] or "(none — housekeeping only, no re-recorded equipment)"
        fu = f"  followups={len(v['followups'])}" if v["followups"] else ""
        print(f"  {v['job_id']:<14} {v['property']:<38} tech={v['technician']:<14} "
              f"client={(v.get('client') or ''):<16} photo={photo}{fu}")


def _fetch_id_token(audience: str) -> str:
    """Google ID token for the fleet's auth-only Cloud Run URL (ADC / SA key /
    metadata server) — same mechanism as dashboard/main.py::_id_token."""
    import google.auth.transport.requests
    import google.oauth2.id_token
    req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(req, audience)


def _last_text(events: Any) -> str:
    out = ""
    for ev in events if isinstance(events, list) else []:
        for p in (ev.get("content") or {}).get("parts") or []:
            if isinstance(p.get("text"), str) and p["text"].strip():
                out = p["text"].strip()
    return out


async def _has_property_fact(pool: Any, job_id: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM memory_facts WHERE subject=$1 AND predicate='property' AND valid_to IS NULL",
            f"job:{job_id}")
    return bool(row)


async def _current_facts(pool: Any, job_id: str) -> list[Any]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT predicate, object FROM memory_facts WHERE subject=$1 AND valid_to IS NULL ORDER BY predicate",
            f"job:{job_id}")


async def _run_turn(client: Any, fleet_url: str, headers: dict[str, str], payload: dict[str, Any]) -> str:
    r = await client.post(f"{fleet_url}/run", headers=headers, json=payload)
    r.raise_for_status()
    return _last_text(r.json())


async def _run_visit(client: Any, pool: Any, fleet_url: str, headers: dict[str, str],
                      visit: dict[str, Any]) -> bool:
    """Run one visit end to end. Returns True iff it ends with a property fact."""
    job_id = visit["job_id"]
    photo_bytes = Path(visit["photo"]).read_bytes() if visit["photo"] else None
    mime = "image/jpeg" if photo_bytes else None

    r = await client.post(
        f"{fleet_url}/apps/foreman_app/users/seed/sessions/{job_id}",
        json={}, headers=headers)
    if r.status_code not in (200, 400, 409):
        r.raise_for_status()

    reply = await _run_turn(client, fleet_url, headers, run_payload(visit, photo_bytes, mime))
    print(f"  reply: {reply}")

    for followup in visit.get("followups") or []:
        reply = await _run_turn(client, fleet_url, headers, _followup_payload(job_id, followup))
        print(f"  follow-up reply: {reply}")

    facts = await _current_facts(pool, job_id)
    has_property = False
    print("  facts:")
    for row in facts:
        print(f"    {row['predicate']}: {row['object']}")
        if row["predicate"] == "property":
            has_property = True
    if not has_property:
        print(f"  FAIL: job:{job_id} ended without a property fact", file=sys.stderr)
    return has_property


async def _run_plan(plan: list[dict[str, Any]], fleet_url: str, db_url: str, force: bool = False) -> int:
    from foreman_app.foreman_core.db import create_pool
    import httpx

    try:
        pool = await create_pool(db_url)
    except Exception as e:
        print(f"error: could not connect to --db-url ({e}); "
              f"is the cloud-sql-proxy tunnel up?", file=sys.stderr)
        return 2
    failures: list[str] = []
    try:
        for i, visit in enumerate(plan):
            job_id = visit["job_id"]
            print(f"\n=== {job_id} — {visit['property']} ({visit['technician']}) ===")
            if not force and await _has_property_fact(pool, job_id):
                print(f"  skip: job:{job_id} already has a property fact (idempotent)")
                continue

            try:
                token = await asyncio.to_thread(_fetch_id_token, fleet_url)
            except Exception as e:
                print(f"  ERROR fetching ID token: {e}", file=sys.stderr)
                failures.append(job_id)
                continue

            headers = {"Authorization": f"Bearer {token}"}
            try:
                async with httpx.AsyncClient(timeout=RUN_TIMEOUT_S) as client:
                    ok = await _run_visit(client, pool, fleet_url, headers, visit)
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
                ok = False
            if not ok:
                failures.append(job_id)

            if i < len(plan) - 1:
                await asyncio.sleep(SLEEP_BETWEEN_VISITS_S)
    finally:
        await pool.close()

    if failures:
        print(f"\n{len(failures)} visit(s) ended without a property fact: {', '.join(failures)}",
              file=sys.stderr)
        return 1
    print(f"\nall {len(plan)} visit(s) recorded a property fact (including any skipped as already-seeded).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the Foreman+ sample workspace through the real fleet.")
    parser.add_argument("--dry-run", action="store_true",
                         help="print the visit plan and exit; no network/DB calls")
    parser.add_argument("--run", action="store_true",
                         help="execute the plan against the live fleet (Vertex-billed)")
    parser.add_argument("--force", action="store_true",
                        help="re-run a visit even if the job already has a property fact")
    parser.add_argument("--only", metavar="JOB_ID",
                         help="run a single visit by job_id instead of the whole plan")
    parser.add_argument("--fleet-url", default=FLEET_URL_DEFAULT,
                         help=f"fleet /run base URL (default: {FLEET_URL_DEFAULT})")
    parser.add_argument("--db-url", default=os.environ.get("FOREMAN_DB_URL", ""),
                         help="Postgres DSN (default: $FOREMAN_DB_URL)")
    args = parser.parse_args(argv)

    plan = build_plan()
    if args.only:
        plan = [v for v in plan if v["job_id"] == args.only]
        if not plan:
            print(f"error: no visit with job_id={args.only!r}", file=sys.stderr)
            return 2

    if not args.run:
        # default AND --dry-run: print, touch nothing.
        _print_plan(plan)
        return 0

    if not args.db_url:
        print("error: --db-url or $FOREMAN_DB_URL is required for --run", file=sys.stderr)
        return 2

    # Fail loudly BEFORE any network call if a photo path is set but missing.
    # Visits with photo=None are fine as-is (housekeeping, nothing to read).
    missing = [v["photo"] for v in plan if v["photo"] and not (ROOT / v["photo"]).is_file()
               and not Path(v["photo"]).is_file()]
    if missing:
        print("error: missing seed photo file(s), aborting before any network call:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 2

    return asyncio.run(_run_plan(plan, args.fleet_url, args.db_url, force=args.force))


if __name__ == "__main__":
    sys.exit(main())
