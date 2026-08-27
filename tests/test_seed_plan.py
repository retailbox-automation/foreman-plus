"""Pure tests for scripts/seed_workspace.py's plan builder and payload shape.

No network, no DB — build_plan()/run_payload() are pure functions over the
VISITS list; --run's network/DB path is exercised manually by the orchestrator
against the live fleet (see scripts/seed_workspace.py's module docstring).
"""
from scripts.seed_workspace import build_plan, run_payload


def test_plan_has_three_properties_and_idempotent_ids():
    plan = build_plan()
    props = {v["property"] for v in plan}
    assert props == {"1187 Lakeshore Dr, Orlando FL 32803", "214 Maple Ct, Orlando FL 32806", "902 Ferncreek Ave, Orlando FL 32806"}
    assert len({v["job_id"] for v in plan}) == len(plan)


def test_run_payload_shape_with_and_without_photo():
    plan = build_plan()
    with_photo = next(v for v in plan if v["photo"])
    p = run_payload(with_photo, photo_bytes=b"\xff\xd8", mime="image/jpeg")
    assert p["session_id"] == with_photo["job_id"] and p["app_name"] == "foreman_app"
    assert with_photo["property"] in p["new_message"]["parts"][0]["text"]
    assert p["new_message"]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
    hk = next(v for v in plan if v["photo"] is None)
    p2 = run_payload(hk, photo_bytes=None, mime=None)
    assert len(p2["new_message"]["parts"]) == 1 and p2["new_message"]["parts"][0]["text"].startswith(f"Job {hk['job_id']}: housekeeping")
