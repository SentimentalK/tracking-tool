import base64
import json
import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Union
import certifi
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

if "SSL_CERT_FILE" not in os.environ:
    os.environ["SSL_CERT_FILE"] = certifi.where()

logger = logging.getLogger(__name__)


class SlackClient:
    """Reusable generic Slack API client without application-specific logic."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("SLACK_TOKEN", "")
        self.client = WebClient(token=self.token)

    def send_message(
        self,
        channel: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        text: str = "bot msg",
    ) -> Dict[str, Any]:
        """Send a message to a Slack channel."""
        try:
            if blocks is not None:
                return self.client.chat_postMessage(channel=channel, blocks=blocks, text=text).data
            return self.client.chat_postMessage(channel=channel, text=text).data
        except SlackApiError as e:
            logger.error("Slack chat_postMessage error: %s", e.response.get("error"))
            raise

    def delete_message(self, channel: str, ts: Union[str, float]) -> Dict[str, Any]:
        """Delete a message from a Slack channel."""
        try:
            return self.client.chat_delete(channel=channel, ts=str(ts)).data
        except SlackApiError as e:
            logger.error("Slack chat_delete error: %s", e.response.get("error"))
            raise

    def post_response(
        self,
        response_url: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        text: Optional[str] = None,
        replace_original: bool = True,
    ) -> requests.Response:
        """Send an update response back to an interactive callback URL."""
        payload: Dict[str, Any] = {"replace_original": replace_original}
        if blocks is not None:
            payload["blocks"] = blocks
        if text is not None:
            payload["text"] = text

        resp = requests.post(response_url, json=payload)
        if resp.status_code != 200:
            logger.error("Slack webhook post_response failed <%s>: %s", resp.status_code, resp.text)
        return resp

    @staticmethod
    def parse_interactive_payload(raw_body: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
        """Parse Slack interactive webhook payload from various input formats."""
        if isinstance(raw_body, dict):
            return raw_body

        if isinstance(raw_body, bytes):
            raw_body = raw_body.decode("utf-8")

        # 1. Direct JSON
        try:
            return json.loads(raw_body)
        except Exception:
            pass

        # 2. Base64 decoded attempt
        decoded_text = raw_body
        try:
            b64_decoded = base64.b64decode(raw_body.encode("ascii")).decode("utf-8")
            decoded_text = b64_decoded
        except Exception:
            pass

        # 3. URL-encoded form format (payload=...)
        if "payload=" in decoded_text:
            parsed = urllib.parse.parse_qs(decoded_text)
            if "payload" in parsed:
                return json.loads(parsed["payload"][0])

        unquoted = urllib.parse.unquote(decoded_text)
        if "payload=" in unquoted:
            parsed = urllib.parse.parse_qs(unquoted)
            if "payload" in parsed:
                return json.loads(parsed["payload"][0])
            idx = unquoted.index("payload=") + len("payload=")
            return json.loads(unquoted[idx:].replace("+", " "))

        return json.loads(unquoted)
