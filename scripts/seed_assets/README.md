# Seed assets

Nameplate photos used by `scripts/seed_workspace.py` to seed the sample
workspace (three properties, seven visits) through the real fleet. They are
inputs to the fleet's own vision reading — the script never writes facts
directly, so what the model reads off these images IS what lands in memory.

## Files

- **`lakeshore-bradford-white.jpg`** — nameplate of an electric residential
  water heater (Bradford White-style), fully legible: brand, model, serial,
  manufacture date, capacity. Used for both Lakeshore Dr visits (`J-LAKE-1`,
  `J-LAKE-2` — same physical unit, a leak visit followed by a callback), so
  the fleet's answer on the callback should be consistent with what it
  already recorded on the first visit.
- **`ferncreek-lg-dryer-worn.jpg`** — nameplate of an electric clothes dryer
  (LG-style), deliberately **worn**: the model designation should still be
  readable, the serial number should not. Used for `J-FERN-1`, to exercise
  the honest-`UNKNOWN` / `source: "plate unreadable"` path from a single
  photo (not a synthetic "no photo at all" case).
- **214 Maple Ct visits need no new photo.** `J-DEMO-134922` and `J-VRTX1`
  are housekeeping-only entries (see `VISITS` in `seed_workspace.py`) that
  attach an address/technician/client to jobs whose equipment facts were
  already recorded earlier in the project from
  `dashboard/static/demo/nameplate.jpg` — that photo is not re-sent, and the
  seeding notes explicitly tell the fleet not to re-record equipment facts.

## These are generated samples, not real photographs

Both images are AI-generated illustrative nameplates (Nano Banana /
Gemini image generation), created for this hackathon submission's sample
workspace only. They depict no real customer, address, or equipment; the
addresses, technician names and client names in `seed_workspace.py`'s
`VISITS` are fictional sample data (`Ridgeline Mechanical · sample
workspace`).

## Before running `--run`

`scripts/seed_workspace.py --dry-run` works with **no files present** in
this directory — it only prints the plan. `--run` needs both files above to
exist here before it starts: the orchestrator generates
`lakeshore-bradford-white.jpg` and `ferncreek-lg-dryer-worn.jpg` (via Nano
Banana) and drops them in this directory first. If a photo path in the plan
is set but the file is missing, the script fails loudly and refuses to make
any network call rather than seeding a visit with the wrong (or no) image.
