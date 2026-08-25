"""A2A exposure of the closer agent — its own Cloud Run service.

The closer is the fleet's CRM-agnostic exit: any downstream system (FSM,
home-warranty authorizer, another fleet) discovers it via the well-known
agent card and asks it to close out a job over the A2A protocol. Boundary
chosen for independent deploy/scale, not because A2A exists.

Run: uvicorn foreman_app.a2a_app:a2a_app --host 0.0.0.0 --port $PORT
"""
import hmac
import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.responses import PlainTextResponse

from .agent import closer

# Card URL fields describe the PUBLIC address (Cloud Run domain), not the
# local bind — uvicorn binds $PORT separately via the Procfile.
a2a_app = to_a2a(
    closer,
    host=os.environ.get("A2A_HOST", "localhost"),
    port=int(os.environ.get("A2A_CARD_PORT", os.environ.get("PORT", "8080"))),
    protocol=os.environ.get("A2A_PROTOCOL", "http"),
)


class _SharedSecretGuard:
    """Discovery stays open; every other path needs X-Foreman-Key.

    A public Cloud Run URL must not be a free LLM-burn endpoint — judges get
    the key in the submission's testing instructions.
    """

    def __init__(self, app, secret: str):
        self.app = app
        self.secret = secret

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not (
            scope["path"].startswith("/.well-known/") or scope["path"] == "/healthz"
        ):
            supplied = ""
            for k, v in scope.get("headers", []):
                if k.decode().lower() == "x-foreman-key":
                    supplied = v.decode()
            if not hmac.compare_digest(supplied, self.secret):
                resp = PlainTextResponse(
                    "missing or invalid X-Foreman-Key", status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


_secret = os.environ.get("A2A_SHARED_SECRET")
if _secret:
    a2a_app.add_middleware(_SharedSecretGuard, secret=_secret)
