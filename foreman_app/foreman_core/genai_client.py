"""Shared google-genai client factory: Vertex AI (ADC) or Developer API key.

GOOGLE_GENAI_USE_VERTEXAI=TRUE routes calls through Vertex AI
(aiplatform.googleapis.com), billed to the project's Cloud Billing account —
trial/promo credits apply there. The API-key path (Gemini Developer API) is
prepay-billed since 2026-03 and is NOT covered by Cloud credits.
"""
import os

from google import genai


def use_vertexai() -> bool:
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")


def make_client() -> genai.Client:
    if use_vertexai():
        return genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", "foreman-hackathon"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    # vertexai=False is load-bearing on the key path: inside GCP the client
    # auto-detects the Vertex surface, which the AQ key's restriction blocks.
    return genai.Client(
        api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"],
        vertexai=False,
    )
