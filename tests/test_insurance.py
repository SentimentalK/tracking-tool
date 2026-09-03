from unittest.mock import patch
import pandas as pd
import pytest

from apps.insurance.config import InsuranceConfig
from apps.insurance.renderer import InsuranceRenderer
from apps.insurance.workflow import InsuranceTracker
from tests.conftest import MockSlackClient, MockTable
from tracker.config import load_env_secrets
from tracker.slack import SlackClient


def build_sample_order_df():
    return pd.DataFrame([
        {
            "notion_id": "11111111-1111-1111-1111-111111111111",
            "保单号": "POL001",
            "状态": "有效保单",
            "缴费倒计时": 0,
            "下次续费时间": "2026-05-10",
            "保费": 5000,
            "缴费期间": "10",
            "最晚缴费时间": "2026-07-10",
            "已缴次数": 2,
            "投保人|姓名": "张三",
            "被保险人|姓名": "李四",
            "投保险种产品名称|产品名称": "重大疾病险",
            "slack时间戳": 12345.0,
        },
        {
            "notion_id": "22222222-2222-2222-2222-222222222222",
            "保单号": "POL002",
            "状态": "有效保单",
            "缴费倒计时": 8,
            "下次续费时间": "2026-05-18",
            "保费": 3000,
            "缴费期间": "20",
            "最晚缴费时间": "2026-07-18",
            "已缴次数": 5,
            "投保人|姓名": "张三",
            "被保险人|姓名": "张三",
            "投保险种产品名称|产品名称": "意外险",
            "slack时间戳": None,
        },
        {
            "notion_id": "33333333-3333-3333-3333-333333333333",
            "保单号": "POL003",
            "状态": "有效保单",
            "缴费倒计时": 5,  # Not in [0, 1, 8, 15]
            "下次续费时间": "2026-05-15",
            "保费": 2000,
            "缴费期间": "10",
            "最晚缴费时间": "2026-07-15",
            "已缴次数": 1,
            "投保人|姓名": "王五",
            "被保险人|姓名": "王五",
            "投保险种产品名称|产品名称": "医疗险",
            "slack时间戳": None,
        },
        {
            "notion_id": "44444444-4444-4444-4444-444444444444",
            "保单号": "POL004",
            "状态": "有效保单",
            "缴费倒计时": -10,  # Overdue within 90 days
            "下次续费时间": "2026-04-20",
            "保费": 4000,
            "缴费期间": "15",
            "最晚缴费时间": "2026-06-20",
            "已缴次数": 3,
            "投保人|姓名": "张三",
            "被保险人|姓名": "张三",
            "投保险种产品名称|产品名称": "人寿险",
            "slack时间戳": None,
        },
        {
            "notion_id": "55555555-5555-5555-5555-555555555555",
            "保单号": "POL005",
            "状态": "有效保单",
            "缴费倒计时": -95,  # Exceeded 90 days overdue
            "下次续费时间": "2026-01-20",
            "保费": 4000,
            "缴费期间": "15",
            "最晚缴费时间": "2026-03-20",
            "已缴次数": 3,
            "投保人|姓名": "张三",
            "被保险人|姓名": "张三",
            "投保险种产品名称|产品名称": "人寿险",
            "slack时间戳": None,
        },
    ])


def build_sample_people_df():
    return pd.DataFrame([
        {"notion_id": "p1", "姓名": "张三", "年龄": 35, "生日": "1991-01-01"},
        {"notion_id": "p2", "姓名": "李四", "年龄": 30, "生日": "1996-02-02"},
        {"notion_id": "p3", "姓名": "王五", "年龄": 40, "生日": "1986-03-03"},
    ])


def create_mock_tracker():
    order_df = build_sample_order_df()
    people_df = build_sample_people_df()
    slack = MockSlackClient()
    config = InsuranceConfig()

    with patch("apps.insurance.workflow.Table") as mock_table_cls:
        tracker = InsuranceTracker(config=config, slack_client=slack)
        tracker.odr = MockTable(order_df)
        tracker.ppl = MockTable(people_df)
        return tracker, slack


def test_env_secrets_validation(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Missing required environment variable"):
        load_env_secrets()

    monkeypatch.setenv("NOTION_TOKEN", "mock-notion-token")
    monkeypatch.setenv("SLACK_TOKEN", "mock-slack-token")
    secrets = load_env_secrets()
    assert secrets.notion_token == "mock-notion-token"
    assert secrets.slack_token == "mock-slack-token"


def test_countdown_reminders_and_expiration():
    tracker, slack = create_mock_tracker()

    # Freeze day to non-Monday (e.g. Wednesday, weekday=2)
    with patch("pandas.Timestamp.now") as mock_now:
        mock_dt = pd.Timestamp("2026-05-13 10:00:00", tz="Asia/Shanghai")
        mock_now.return_value = mock_dt

        metrics = tracker.run_daily()

        # POL001 (0 days) and POL002 (8 days) should trigger reminders
        # POL003 (5 days) should not trigger
        # POL004 (-10 days) should not trigger on Wednesday
        assert metrics["short_period_reminders"] == 2
        assert metrics["unpaid_reminders"] == 0
        assert metrics["expired"] == 1

        # POL001 had an existing slack timestamp: 12345.0, so it should have been deleted
        assert len(slack.deleted_messages) == 1
        assert slack.deleted_messages[0]["ts"] == "12345.0"

        # 2 reminder messages sent in total
        assert len(slack.sent_messages) == 2

        # POL005 should be marked as "失效"
        assert tracker.odr.df.loc["55555555-5555-5555-5555-555555555555", "状态"] == "失效"


def test_monday_overdue_reminders():
    tracker, slack = create_mock_tracker()

    # Freeze day to Monday (e.g. 2026-05-11, weekday=0)
    with patch("pandas.Timestamp.now") as mock_now:
        mock_dt = pd.Timestamp("2026-05-11 10:00:00", tz="Asia/Shanghai")
        mock_now.return_value = mock_dt

        metrics = tracker.run_daily()

        # POL001 (0) + POL002 (8) = 2 short period
        # POL004 (-10) = 1 unpaid reminder
        assert metrics["short_period_reminders"] == 2
        assert metrics["unpaid_reminders"] == 1
        assert len(slack.sent_messages) == 3


def test_force_unpaid_and_dry_run_reminders():
    tracker, slack = create_mock_tracker()

    # Freeze day to Wednesday (weekday=2)
    with patch("pandas.Timestamp.now") as mock_now:
        mock_dt = pd.Timestamp("2026-05-13 10:00:00", tz="Asia/Shanghai")
        mock_now.return_value = mock_dt

        # When force_unpaid=True, POL004 (-10) should trigger even on Wednesday
        metrics = tracker.run_daily(force_unpaid=True, dry_run=False)
        assert metrics["short_period_reminders"] == 2
        assert metrics["unpaid_reminders"] == 1
        assert len(slack.sent_messages) == 3

    # Test dry_run=True: zero messages sent, nothing written
    tracker_dry, slack_dry = create_mock_tracker()
    with patch("pandas.Timestamp.now") as mock_now:
        mock_dt = pd.Timestamp("2026-05-13 10:00:00", tz="Asia/Shanghai")
        mock_now.return_value = mock_dt

        metrics_dry = tracker_dry.run_daily(force_unpaid=True, dry_run=True)
        assert metrics_dry["dry_run"] is True
        assert len(slack_dry.sent_messages) == 0
        assert len(tracker_dry.odr.written_changes) == 0


def test_action_paid_standard():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"

    # Initial state: 次数=2, 下次续费时间=2026-05-10
    payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "elements": []},
            ]
        },
    }

    result = tracker.handle_action(payload)
    assert result["status"] == "ok"

    row = tracker.odr.df.loc[notion_id]
    assert row["已缴次数"] == 3
    assert row["下次续费时间"] == "2027-05-10"
    assert row["状态"] == "有效保单"  # 3 < 10, not yet complete
    assert pd.isna(row["slack时间戳"]) or row["slack时间戳"] is None

    # Verify webhook responses: first "working", then "ok" with undo button
    assert len(slack.post_responses) == 2
    assert slack.post_responses[0]["blocks"][-1]["text"]["text"] == ":pray: 数据同步中"
    assert "数据同步成功" in slack.post_responses[1]["blocks"][-2]["text"]["text"]
    undo_button = slack.post_responses[1]["blocks"][-1]["elements"][0]
    assert undo_button["text"]["text"] == "↩️ 撤销操作 (Undo)"
    assert len(undo_button["value"]) <= 2000


def test_action_paid_transition_to_complete():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"

    # Set 已缴次数 to 9, 缴费期间 is "10"
    tracker.odr.df.loc[notion_id, "已缴次数"] = 9

    payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "elements": []},
            ]
        },
    }

    tracker.handle_action(payload)
    row = tracker.odr.df.loc[notion_id]
    assert row["已缴次数"] == 10
    assert row["状态"] == "已缴满"


def test_action_paid_non_integer_period_does_not_complete():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"

    # Set 缴费期间 to "终身"
    tracker.odr.df.loc[notion_id, "缴费期间"] = "终身"
    tracker.odr.df.loc[notion_id, "已缴次数"] = 99

    payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "elements": []},
            ]
        },
    }

    tracker.handle_action(payload)
    row = tracker.odr.df.loc[notion_id]
    assert row["已缴次数"] == 100
    assert row["状态"] == "有效保单"


def test_action_destory():
    tracker, slack = create_mock_tracker()
    notion_id = "22222222-2222-2222-2222-222222222222"

    payload = {
        "actions": [{"value": "destory"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "elements": []},
            ]
        },
    }

    result = tracker.handle_action(payload)
    assert result["status"] == "ok"

    row = tracker.odr.df.loc[notion_id]
    assert row["状态"] == "失效"
    assert pd.isna(row["slack时间戳"]) or row["slack时间戳"] is None


def test_slack_interactive_payload_parsing():
    raw_dict = {"actions": [{"value": "paid"}]}
    assert SlackClient.parse_interactive_payload(raw_dict) == raw_dict

    # URL encoded payload=...
    import json
    import urllib.parse
    import base64

    json_str = json.dumps({"actions": [{"value": "destory"}]})
    url_encoded = f"payload={urllib.parse.quote(json_str)}"
    assert SlackClient.parse_interactive_payload(url_encoded)["actions"][0]["value"] == "destory"

    # Base64 encoded payload
    b64_encoded = base64.b64encode(url_encoded.encode("ascii")).decode("ascii")
    assert SlackClient.parse_interactive_payload(b64_encoded)["actions"][0]["value"] == "destory"


def test_renderer_output():
    renderer = InsuranceRenderer(user_id="U12345", admin_id="U99999")
    blocks = renderer.render_reminder_card(
        notion_id="notion-123",
        policy_no="P-100",
        applicant_name="张三",
        applicant_age=30,
        applicant_birthday="1990-01-01",
        insured_name="李四",
        insured_age=5,
        insured_birthday="2021-01-01",
        product_name="少儿成长险",
        next_pay_date="2200-12-31",  # should be replaced with 终身
        countdown=8,
        premium=1200,
        payment_period="10",
        latest_pay_date="2200-12-31",
    )

    # Check button values
    action_block = blocks[-1]
    assert action_block["elements"][0]["value"] == "paid"
    assert action_block["elements"][1]["value"] == "destory"

    # Check 2200-12-31 replaced by 终身
    section_text = blocks[3]["text"]["text"]
    assert "终身" in section_text
    assert "2200-12-31" not in section_text
    assert "<@U12345>" in section_text


def test_undo_paid_restores_original_state():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"

    # Step 1: Execute paid action
    paid_payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "container": {"message_ts": "1788888888.123456"},
        "message": {
            "ts": "1788888888.123456",
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "block_id": "policy_actions", "elements": []},
            ],
        },
    }

    res = tracker.handle_action(paid_payload)
    assert res["status"] == "ok"
    undo_payload_obj = res["undo_payload"]

    # Verify state after paid: count=3, date=2027-05-10
    row_after_paid = tracker.odr.df.loc[notion_id]
    assert row_after_paid["已缴次数"] == 3
    assert row_after_paid["下次续费时间"] == "2027-05-10"
    assert pd.isna(row_after_paid["slack时间戳"]) or row_after_paid["slack时间戳"] is None

    # Step 2: User clicks [Undo]
    import json
    undo_button_value = json.dumps(undo_payload_obj, ensure_ascii=False)
    assert len(undo_button_value) <= 2000

    undo_request_payload = {
        "actions": [{"value": undo_button_value}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "container": {"message_ts": "1788888888.123456"},
        "message": {
            "ts": "1788888888.123456",
            "blocks": slack.post_responses[-1]["blocks"],
        },
    }

    undo_res = tracker.handle_action(undo_request_payload)
    assert undo_res["status"] == "ok"

    # Verify state after undo: count=2, date=2026-05-10, slack时间戳 restored
    row_after_undo = tracker.odr.df.loc[notion_id]
    assert row_after_undo["已缴次数"] == 2
    assert row_after_undo["下次续费时间"] == "2026-05-10"
    assert row_after_undo["状态"] == "有效保单"
    assert row_after_undo["slack时间戳"] == 1788888888.123456

    # Verify restored buttons on Slack card
    last_response_blocks = slack.post_responses[-1]["blocks"]
    action_block = [b for b in last_response_blocks if b.get("block_id") == "policy_actions"][0]
    assert action_block["elements"][0]["value"] == "paid"
    assert action_block["elements"][1]["value"] == "destory"


def test_undo_paid_transition_from_complete():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"
    tracker.odr.df.loc[notion_id, "已缴次数"] = 9  # 缴费期间 is "10"

    paid_payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "block_id": "policy_actions", "elements": []},
            ],
        },
    }

    res = tracker.handle_action(paid_payload)
    assert tracker.odr.df.loc[notion_id, "状态"] == "已缴满"

    # Click Undo
    import json
    undo_payload_obj = res["undo_payload"]
    undo_request = {
        "actions": [{"value": json.dumps(undo_payload_obj)}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": slack.post_responses[-1]["blocks"],
        },
    }

    undo_res = tracker.handle_action(undo_request)
    assert undo_res["status"] == "ok"
    assert tracker.odr.df.loc[notion_id, "已缴次数"] == 9
    assert tracker.odr.df.loc[notion_id, "状态"] == "有效保单"


def test_undo_destory_restores_active_policy():
    tracker, slack = create_mock_tracker()
    notion_id = "22222222-2222-2222-2222-222222222222"

    destory_payload = {
        "actions": [{"value": "destory"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "block_id": "policy_actions", "elements": []},
            ],
        },
    }

    res = tracker.handle_action(destory_payload)
    assert tracker.odr.df.loc[notion_id, "状态"] == "失效"

    import json
    undo_payload_obj = res["undo_payload"]
    undo_request = {
        "actions": [{"value": json.dumps(undo_payload_obj)}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": slack.post_responses[-1]["blocks"],
        },
    }

    undo_res = tracker.handle_action(undo_request)
    assert undo_res["status"] == "ok"
    assert tracker.odr.df.loc[notion_id, "状态"] == "有效保单"


def test_undo_concurrency_conflict_refuses_overwrite():
    tracker, slack = create_mock_tracker()
    notion_id = "11111111-1111-1111-1111-111111111111"

    # Step 1: Execute paid
    paid_payload = {
        "actions": [{"value": "paid"}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": [
                {"type": "context", "elements": [{"text": f"notion_id: {notion_id}"}]},
                {"type": "actions", "block_id": "policy_actions", "elements": []},
            ],
        },
    }
    res = tracker.handle_action(paid_payload)
    undo_payload_obj = res["undo_payload"]

    # Step 2: Simulate external concurrent manual edit in Notion (e.g. admin changed count to 5)
    tracker.odr.df.loc[notion_id, "已缴次数"] = 5

    # Step 3: User clicks Undo
    import json
    undo_request = {
        "actions": [{"value": json.dumps(undo_payload_obj)}],
        "response_url": "https://hooks.slack.com/actions/123/456",
        "message": {
            "ts": "123.456",
            "blocks": slack.post_responses[-1]["blocks"],
        },
    }

    undo_res = tracker.handle_action(undo_request)
    # Must refuse overwrite!
    assert undo_res["status"] == "conflict"
    # Current Notion count must remain 5, not reverted to 2!
    assert tracker.odr.df.loc[notion_id, "已缴次数"] == 5

    # Verify conflict warning block sent to Slack
    last_response_blocks = slack.post_responses[-1]["blocks"]
    conflict_block = [b for b in last_response_blocks if b.get("block_id") == "policy_conflict"][0]
    assert "外部修改" in conflict_block["text"]["text"]


def test_json_normalization_handles_numpy_and_nans():
    import numpy as np
    from apps.insurance.workflow import _normalize_val

    assert _normalize_val(np.int64(10)) == 10
    assert isinstance(_normalize_val(np.int64(10)), int)
    assert _normalize_val(np.float64(3.14)) == 3.14
    assert _normalize_val(pd.Timestamp("2026-05-10")) == "2026-05-10"
    assert _normalize_val(pd.NA) is None
    assert _normalize_val(float("nan")) is None
    assert _normalize_val(None) is None
    assert _normalize_val("有效保单") == "有效保单"

