"""Generate the office intro's field-scene clip with Veo 3.1 on Vertex AI.

The clip in dashboard/static/app/assets/hero.mp4 (a technician reading a job
card on site) is generated, not stock — this script is its provenance and
regenerates it on demand. Small on-screen UI text degrades in any video model,
so the clip is shown small and muted; readable text belongs in keyframes.

Model: veo-3.1-generate-001 (GA) via :predictLongRunning — generation is a
long-running operation (minutes): poll :fetchPredictOperation until done, the
video comes back base64 in response.videos[]. Auth: plain ADC.

Usage:
    python scripts/generate_hero_clip.py [--out hero.mp4] [--prompt "..."]
"""
import argparse
import base64
import json
import os
import time
import urllib.request

import google.auth
import google.auth.transport.requests

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "foreman-hackathon")
MODEL = "veo-3.1-generate-001"
BASE = (f"https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/us-central1/publishers/google/models/{MODEL}")

DEFAULT_PROMPT = (
    "A field service technician in a hi-vis vest and hard hat on a job site "
    "at golden hour, reading a rugged tablet showing a job card, shallow "
    "depth of field, warm natural light, steady close shot, photorealistic"
)


def _call(url: str, payload: dict, token: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="hero.mp4")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--seconds", type=int, default=8, choices=(4, 6, 8))
    args = ap.parse_args()

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())

    op = _call(f"{BASE}:predictLongRunning", {
        "instances": [{"prompt": args.prompt}],
        "parameters": {"durationSeconds": args.seconds, "aspectRatio": "16:9",
                       "sampleCount": 1},
    }, creds.token)["name"]
    print(f"operation {op} — polling (a clip takes minutes)")

    while True:
        time.sleep(20)
        creds.refresh(google.auth.transport.requests.Request())
        res = _call(f"{BASE}:fetchPredictOperation", {"operationName": op},
                    creds.token)
        if res.get("done"):
            break
        print("  …still generating")

    videos = (res.get("response") or {}).get("videos") or []
    if not videos:
        raise SystemExit(f"no video in response: {json.dumps(res)[:400]}")
    with open(args.out, "wb") as f:
        f.write(base64.b64decode(videos[0]["bytesBase64Encoded"]))
    print(f"wrote {args.out} — model {MODEL}")


if __name__ == "__main__":
    main()
