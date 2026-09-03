import json
import time
import urllib.parse
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from slack_sdk.signature import SignatureVerifier

from server import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_slack_interactions_missing_secret_returns_400(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_UNSIGNED_SLACK", raising=False)

    response = client.post("/slack/interactions", content=b"payload={}")
    assert response.status_code == 400
    assert "SLACK_SIGNING_SECRET is required" in response.text


def test_slack_interactions_missing_headers_returns_401(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.delenv("ALLOW_UNSIGNED_SLACK", raising=False)

    response = client.post("/slack/interactions", content=b"payload={}")
    assert response.status_code == 401
    assert "Missing Slack signature headers" in response.text


def test_slack_interactions_invalid_signature_returns_401(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.delenv("ALLOW_UNSIGNED_SLACK", raising=False)

    headers = {
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=invalid_signature_hex",
    }
    response = client.post("/slack/interactions", content=b"payload={}", headers=headers)
    assert response.status_code == 401
    assert "Invalid Slack signature" in response.text


def test_slack_interactions_valid_signature_returns_200_and_runs_background(monkeypatch):
    secret = "test-signing-secret"
    monkeypatch.setenv("SLACK_SIGNING_SECRET", secret)
    monkeypatch.delenv("ALLOW_UNSIGNED_SLACK", raising=False)

    raw_payload_dict = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/xxx",
        "message": {
            "blocks": [
                {"elements": [{"text": "notion_id: 11111111-1111-1111-1111-111111111111"}]}
            ]
        },
    }
    body_str = f"payload={urllib.parse.quote(json.dumps(raw_payload_dict))}"
    raw_body_bytes = body_str.encode("utf-8")

    ts = str(int(time.time()))
    verifier = SignatureVerifier(secret)
    signature = verifier.generate_signature(timestamp=ts, body=body_str)

    headers = {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": signature,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    with patch("server.handle_action") as mock_handle:
        response = client.post("/slack/interactions", content=raw_body_bytes, headers=headers)
        assert response.status_code == 200
        assert response.text == "ok"
        mock_handle.assert_called_once_with(raw_body_bytes)


def test_slack_interactions_unsigned_dev_mode(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSIGNED_SLACK", "true")
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

    body_bytes = b"payload={}"
    with patch("server.handle_action") as mock_handle:
        response = client.post("/slack/interactions", content=body_bytes)
        assert response.status_code == 200
        assert response.text == "ok"
        mock_handle.assert_called_once_with(body_bytes)
