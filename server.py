import logging
import os
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, Request, Response, status
from slack_sdk.signature import SignatureVerifier

from apps.insurance.workflow import handle_action

logger = logging.getLogger("tracker.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()
    allow_unsigned = os.environ.get("ALLOW_UNSIGNED_SLACK", "").lower() in ("true", "1")
    if not signing_secret and not allow_unsigned:
        logger.warning(
            "SLACK_SIGNING_SECRET is not configured. Webhooks to /slack/interactions will return 400."
        )
    elif allow_unsigned:
        logger.warning(
            "ALLOW_UNSIGNED_SLACK=true is enabled. Request signatures will NOT be verified (dev mode only)."
        )
    yield


app = FastAPI(title="Tracking Tool Webhook Server", lifespan=lifespan)


@app.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    """Liveness and readiness probe endpoint for Kubernetes / K3s."""
    return {"status": "ok"}


@app.post("/slack/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack interactive component callbacks with immediate 200 ACK and background execution."""
    raw_body = await request.body()

    allow_unsigned = os.environ.get("ALLOW_UNSIGNED_SLACK", "").lower() in ("true", "1")
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()

    # 1. Fail closed: enforce signing secret verification unless explicitly opted out
    if not allow_unsigned:
        if not signing_secret:
            logger.error("Rejecting request: SLACK_SIGNING_SECRET is not configured.")
            return Response(
                status_code=status.HTTP_400_BAD_REQUEST,
                content="SLACK_SIGNING_SECRET is required but not configured.",
            )

        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        signature = request.headers.get("X-Slack-Signature")

        if not timestamp or not signature:
            logger.warning("Rejecting request: Missing X-Slack-Request-Timestamp or X-Slack-Signature headers.")
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content="Missing Slack signature headers.",
            )

        verifier = SignatureVerifier(signing_secret)
        body_text = raw_body.decode("utf-8", errors="replace")
        if not verifier.is_valid(body=body_text, timestamp=timestamp, signature=signature):
            logger.warning("Rejecting request: Invalid Slack signature or expired timestamp.")
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content="Invalid Slack signature.",
            )

    # 2. Schedule business logic execution asynchronously in background
    background_tasks.add_task(handle_action, raw_body)

    # 3. Immediately return HTTP 200 OK (< 3 seconds ACK requirement)
    return Response(status_code=status.HTTP_200_OK, content="ok")
