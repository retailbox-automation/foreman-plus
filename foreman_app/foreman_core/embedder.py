"""Embeddings for semantic recall (gemini-embedding-001, 768 dims pinned)."""
import os

from google import genai
from google.genai import types

EMBED_MODEL = "gemini-embedding-001"
DIM = 768  # MUST match vector(768) in schema.sql — pinned on every call

_TASK = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GeminiEmbedder:
    def __init__(self, model: str = EMBED_MODEL):
        self.model = model
        # vertexai=False is load-bearing: same AQ-key routing gotcha as verifier
        self._client = genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"],
            vertexai=False,
        )

    async def embed(self, text: str, kind: str = "document") -> list[float]:
        resp = await self._client.aio.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=_TASK[kind], output_dimensionality=DIM,
            ),
        )
        emb = (resp.embeddings or [None])[0]
        values = getattr(emb, "values", None) or []
        if len(values) != DIM:
            raise ValueError(f"embedding dim {len(values)} != {DIM}")
        return list(values)
