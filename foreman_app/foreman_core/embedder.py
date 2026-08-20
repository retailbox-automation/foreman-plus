"""Embeddings for semantic recall (gemini-embedding-001, 768 dims pinned)."""
from google.genai import types

from .genai_client import make_client

EMBED_MODEL = "gemini-embedding-001"
DIM = 768  # MUST match vector(768) in schema.sql — pinned on every call

_TASK = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GeminiEmbedder:
    def __init__(self, model: str = EMBED_MODEL):
        self.model = model
        self._client = make_client()

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
