"""LLM verifier for the write-gate: judges proposals against existing facts."""
import json
import os

from google import genai
from google.genai import types

from .gate import Proposal, Verdict

DEFAULT_MODEL = "gemini-3.6-flash"

_INSTRUCTION = """You are the write-gate verifier of a shared agent memory.
An agent proposes to write one fact. Judge it against the existing facts for the
same subject. REJECT if the proposal contradicts existing facts, is physically
implausible, or is malformed. Approve only facts consistent with the record.
When genuinely uncertain, reject — memory integrity outweighs recall.
Return JSON: {"approved": bool, "reason": "<one short sentence>"}."""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "approved": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["approved", "reason"],
}


class GeminiVerifier:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._client = genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
        )

    async def verify(self, proposal: Proposal, existing_facts: list[dict]) -> Verdict:
        payload = {
            "proposal": {
                "subject": proposal.subject,
                "predicate": proposal.predicate,
                "object": proposal.object,
                "proposed_by": proposal.proposed_by,
            },
            "existing_facts": [
                {
                    "predicate": f.get("predicate"),
                    "object": f.get("object"),
                    "source_agent": f.get("source_agent"),
                }
                for f in existing_facts
            ],
        }
        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=json.dumps(payload),
            config=types.GenerateContentConfig(
                system_instruction=_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0,
            ),
        )
        if not resp.text:
            raise ValueError("empty verifier response")  # gate fails closed on this
        data = json.loads(resp.text)
        return Verdict(
            approved=bool(data["approved"]),
            reason=str(data["reason"]),
            model=self.model,
        )
