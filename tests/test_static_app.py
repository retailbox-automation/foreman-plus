"""Smoke checks on the static office seat: the shell wires the right files,
the router covers every route, and the LEDGER tokens are the ones shipped.

These are cheap structural guards, not a substitute for the click-test: they
catch a renamed asset or a dropped route in CI, where no browser runs.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_office_app_files_exist_and_reference_routes():
    html = (REPO / "dashboard/static/app/index.html").read_text()
    js = (REPO / "dashboard/static/app/app.js").read_text()
    css = (REPO / "dashboard/static/app/app.css").read_text()
    assert "/static/app/app.js" in html and "/static/app/app.css" in html
    for route in ["#/intro", "#/properties", "#/property/", "#/job/", "#/jobs", "#/ledger"]:
        assert route in js, route
    for endpoint in ["/api/properties", "/api/property/", "/api/job/", "/api/state",
                     "/api/demo/run", "/api/demo/status"]:
        assert endpoint in js, endpoint
    assert "#2C5CD8" in css and "Inter" in html and "IBM Plex Mono" in html
    assert "digest" not in css.lower()
    assert "What the gate refused" in js and ".refusal" in css and "refusals" in js


def test_tech_app_files_exist_and_reference_capture_apis():
    html = (REPO / "dashboard/static/tech/index.html").read_text()
    js = (REPO / "dashboard/static/tech/tech.js").read_text()
    assert 'capture="environment"' in html
    for token in ["MediaRecorder", "/api/intake", "/api/intake/status", "/api/property/",
                  "/api/job/", "FormData"]:
        assert token in js


def test_job_page_shows_gate_and_recall_without_a_click():
    js = (REPO / "dashboard/static/app/app.js").read_text()
    assert '<details class="gate" open>' in js
    assert "No similar case on record yet" in js


def test_provenance_opens_a_modal_not_a_popover():
    html = (REPO / "dashboard/static/app/index.html").read_text()
    js = (REPO / "dashboard/static/app/app.js").read_text()
    css = (REPO / "dashboard/static/app/app.css").read_text()
    assert 'id="modal"' in html and 'aria-modal="true"' in html
    assert "function evidence(" in js and ".modal" in css and "Passed the write-gate as entry" in js


def test_demo_run_shows_a_recap_when_it_finishes():
    js = (REPO / "dashboard/static/app/app.js").read_text()
    css = (REPO / "dashboard/static/app/app.css").read_text()
    assert "Run complete" in js and "/api/demo/status" in js and ".recap-stats" in css
