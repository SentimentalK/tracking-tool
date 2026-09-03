import pytest
import pandas as pd
from unittest.mock import MagicMock
from tracker.slack import SlackClient
from tracker.notion import Table


class MockTable:
    """Mock of tracker.notion.Table for offline unit testing."""

    def __init__(self, df: pd.DataFrame):
        self._df = df.copy()
        if "notion_id" in self._df.columns:
            self._df = self._df.set_index("notion_id", drop=False)
        self._merged_df = self._df.copy()
        self.schemas = {col: "rich_text" for col in self._df.columns}
        self.relations = {}
        self.written_changes = []

    @property
    def df(self):
        return self._df

    @property
    def merged_df(self):
        return self._merged_df

    def update_where_index(self, IS, SET, TO):
        self._df.loc[IS, SET] = TO

    def writes(self, with_reference_table=True):
        self._merged_df = self._df.copy()
        self.written_changes.append(self._df.copy())


class MockSlackClient:
    """Mock Slack client tracking outgoing messages and actions."""

    def __init__(self):
        self.sent_messages = []
        self.deleted_messages = []
        self.post_responses = []

    def send_message(self, channel, blocks=None, text="bot msg"):
        call_info = {"channel": channel, "blocks": blocks, "text": text, "ts": "123456.789"}
        self.sent_messages.append(call_info)
        return {"ok": True, "ts": "123456.789"}

    def delete_message(self, channel, ts):
        call_info = {"channel": channel, "ts": ts}
        self.deleted_messages.append(call_info)
        return {"ok": True}

    def post_response(self, response_url, blocks=None, text=None, replace_original=True):
        call_info = {
            "response_url": response_url,
            "blocks": blocks,
            "text": text,
            "replace_original": replace_original,
        }
        self.post_responses.append(call_info)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        return mock_resp

    @staticmethod
    def parse_interactive_payload(raw_body):
        return SlackClient.parse_interactive_payload(raw_body)
