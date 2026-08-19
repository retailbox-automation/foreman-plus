"""Live activity feed (Firestore): real-time fan-out for the dashboard.

Postgres (facts + journal) stays the system of record. The feed is append-only
per-event docs — no hot single document (Firestore write-throughput pattern).
Auth: ADC (attached SA on Cloud Run, GOOGLE_APPLICATION_CREDENTIALS locally) —
the Gemini AQ. API key does NOT work for google-cloud client libraries.
"""
from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient

COLLECTION = "activity"


class FirestoreActivityFeed:
    def __init__(self, project: str, collection: str = COLLECTION):
        self._db = AsyncClient(project=project)
        self._collection = collection

    async def publish(self, event: dict) -> None:
        doc = dict(event)
        doc["ts"] = firestore.SERVER_TIMESTAMP
        await self._db.collection(self._collection).add(doc)

    async def recent(self, limit: int = 50) -> list[dict]:
        q = (self._db.collection(self._collection)
             .order_by("ts", direction=firestore.Query.DESCENDING)
             .limit(limit))
        return [d.to_dict() async for d in q.stream()]
