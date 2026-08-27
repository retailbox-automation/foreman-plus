"""Smoke tests for the two static front-ends served by the dashboard.

They are deliberately shallow: they assert that the files exist and that they
reach for the real browser capture APIs and the real workspace endpoints, so a
refactor cannot silently turn the seats into mock-ups.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_tech_app_files_exist_and_reference_capture_apis():
    html = (REPO / "dashboard/static/tech/index.html").read_text()
    js = (REPO / "dashboard/static/tech/tech.js").read_text()
    assert 'capture="environment"' in html
    for token in ["MediaRecorder", "/api/intake", "/api/intake/status", "/api/property/",
                  "/api/job/", "FormData"]:
        assert token in js
