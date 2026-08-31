"""Generate the demo's ambient wait track with Lyria on Vertex AI.

A judge's "Run the demo" drives the real fleet, which takes a couple of
minutes under Vertex throttling — this 30-second loop is what the optional
"♪ Lyria while you wait" toggle on the run line plays. Generated ONCE and
committed as a static asset (dashboard/static/app/assets/lyria-wait.mp3);
this script is the provenance for that file, and regenerates it on demand.

Model: lyria-002 (GA) via Vertex AI :predict — returns base64 WAV
(48 kHz stereo, ~30 s). Auth: plain ADC, same project as the fleet.

Usage:
    python scripts/generate_wait_track.py [--out lyria-wait.wav] [--prompt "..."]
    ffmpeg -i lyria-wait.wav -codec:a libmp3lame -b:a 128k \
        dashboard/static/app/assets/lyria-wait.mp3
"""
import argparse
import base64
import json
import os
import urllib.request

import google.auth
import google.auth.transport.requests

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "foreman-hackathon")
MODEL = "lyria-002"
URL = (f"https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJECT}"
       f"/locations/us-central1/publishers/google/models/{MODEL}:predict")

DEFAULT_PROMPT = (
    "Calm, warm instrumental ambient for a small workshop office: soft felt "
    "piano and gentle mallets over a quiet room tone, slow and steady, no "
    "drums, no melody hook, unobtrusive background music for waiting, loopable"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="lyria-wait.wav")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = ap.parse_args()

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())

    body = json.dumps({"instances": [{"prompt": args.prompt}],
                       "parameters": {"sampleCount": 1}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        preds = json.load(r)["predictions"]

    wav = base64.b64decode(preds[0]["bytesBase64Encoded"])
    with open(args.out, "wb") as f:
        f.write(wav)
    print(f"wrote {args.out} ({len(wav)} bytes) — model {MODEL}")


if __name__ == "__main__":
    main()
