import datetime
import pandas as pd
import pytest

from apps.birthday.config import BirthdayConfig
from apps.birthday.workflow import BirthdayTracker
from tests.conftest import MockTable, MockSlackClient


def create_birthday_tracker(people_df: pd.DataFrame, timezone: str = "Asia/Shanghai"):
    config = BirthdayConfig(
        slack_channel="#test-birthday",
        timezone=timezone,
    )
    mock_people = MockTable(people_df)
    mock_slack = MockSlackClient()
    tracker = BirthdayTracker(
        config=config,
        slack_client=mock_slack,
        people_table=mock_people,
    )
    return tracker, mock_slack


def test_on_the_day_birthday_with_age():
    today = datetime.date(2026, 5, 10)
    df = pd.DataFrame([
        {
            "姓名": "张三",
            "生日": "1996-05-10",
            "亲属关系": None,
        }
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    assert len(res["on_the_day"]) == 1
    assert res["on_the_day"][0]["name"] == "张三"
    assert res["on_the_day"][0]["turning_age"] == 30

    msg = tracker.render_on_the_day_message(res["on_the_day"])
    assert "Today is 张三's birthday, turns 30 years old 🧁" in msg


def test_advance_10_days_birthday_with_age():
    today = datetime.date(2026, 5, 10)
    df = pd.DataFrame([
        {
            "姓名": "李四",
            "生日": "1990-05-20",
            "亲属关系": "同事",
        }
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    assert len(res["in_advance"]) == 1
    assert res["in_advance"][0]["name"] == "李四 (同事)"
    assert res["in_advance"][0]["turning_age"] == 36

    msg = tracker.render_advance_message(res["in_advance"])
    assert "李四 (同事) has 10 days until 36's birthday 🧁" in msg
    assert "Don't forget to buy gifts 🎈" in msg


def test_sentinel_1900_suppresses_age():
    today = datetime.date(2026, 8, 18)
    df = pd.DataFrame([
        {
            "姓名": "白爵明",
            "生日": "1900-08-18",
            "亲属关系": None,
        },
        {
            "姓名": "韩林",
            "生日": "1900-08-28",
            "亲属关系": None,
        },
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    # On the day: 白爵明
    assert len(res["on_the_day"]) == 1
    assert res["on_the_day"][0]["name"] == "白爵明"
    assert res["on_the_day"][0]["turning_age"] is None
    day_msg = tracker.render_on_the_day_message(res["on_the_day"])
    assert "Today is 白爵明's birthday! 🧁" in day_msg
    assert "years old" not in day_msg

    # In advance: 韩林
    assert len(res["in_advance"]) == 1
    assert res["in_advance"][0]["name"] == "韩林"
    assert res["in_advance"][0]["turning_age"] is None
    adv_msg = tracker.render_advance_message(res["in_advance"])
    assert "韩林 has 10 days until birthday 🧁" in adv_msg
    assert "'s birthday" not in adv_msg


def test_year_rollover_december_to_january():
    # December 22, next occurrence is January 1st next year -> days_until == 10
    today = datetime.date(2026, 12, 22)
    df = pd.DataFrame([
        {
            "姓名": "王五",
            "生日": "2000-01-01",
            "亲属关系": None,
        }
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    assert len(res["in_advance"]) == 1
    assert res["in_advance"][0]["name"] == "王五"
    # In 2027-01-01, turning 27
    assert res["in_advance"][0]["turning_age"] == 27


def test_birthday_already_passed_this_year():
    # Today is June 15, birthday was March 1st
    today = datetime.date(2026, 6, 15)
    df = pd.DataFrame([
        {
            "姓名": "赵六",
            "生日": "1990-03-01",
            "亲属关系": None,
        }
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    # Not today and not in 10 days
    assert len(res["on_the_day"]) == 0
    assert len(res["in_advance"]) == 0


def test_february_29_leap_year_handling():
    # Born on leap day 2000-02-29. In non-leap year 2026, falls back to Feb 28.
    today = datetime.date(2026, 2, 28)
    df = pd.DataFrame([
        {
            "姓名": "闰月友",
            "生日": "2000-02-29",
            "亲属关系": None,
        }
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    assert len(res["on_the_day"]) == 1
    assert res["on_the_day"][0]["name"] == "闰月友"
    assert res["on_the_day"][0]["turning_age"] == 26


def test_empty_or_invalid_birthday_skipped():
    today = datetime.date(2026, 5, 10)
    df = pd.DataFrame([
        {"姓名": None, "生日": "1990-05-10", "亲属关系": None},
        {"姓名": "空生日", "生日": None, "亲属关系": None},
        {"姓名": "非日期", "生日": "invalid-date-string", "亲属关系": None},
    ])
    tracker, slack = create_birthday_tracker(df)
    res = tracker.calculate_occurrences(today, df)

    assert len(res["on_the_day"]) == 0
    assert len(res["in_advance"]) == 0


def test_dry_run_does_not_send_messages(monkeypatch):
    # Mock current date to 2026-05-10
    fake_now = pd.Timestamp("2026-05-10 10:00:00", tz="Asia/Shanghai")
    monkeypatch.setattr(pd.Timestamp, "now", lambda tz=None: fake_now)

    df = pd.DataFrame([
        {"姓名": "张三", "生日": "1996-05-10", "亲属关系": None},
        {"姓名": "李四", "生日": "1990-05-20", "亲属关系": None},
    ])
    tracker, slack = create_birthday_tracker(df)

    result = tracker.run_daily(dry_run=True)
    assert result["dry_run"] is True
    assert result["messages_sent"] == 0
    assert len(result["birthdays_today"]) == 1
    assert len(result["birthdays_in_10_days"]) == 1
    assert len(slack.sent_messages) == 0


def test_live_run_sends_messages(monkeypatch):
    # Mock current date to 2026-05-10
    fake_now = pd.Timestamp("2026-05-10 10:00:00", tz="Asia/Shanghai")
    monkeypatch.setattr(pd.Timestamp, "now", lambda tz=None: fake_now)

    df = pd.DataFrame([
        {"姓名": "张三", "生日": "1996-05-10", "亲属关系": None},
        {"姓名": "李四", "生日": "1990-05-20", "亲属关系": None},
    ])
    tracker, slack = create_birthday_tracker(df)

    result = tracker.run_daily(dry_run=False)
    assert result["dry_run"] is False
    assert result["messages_sent"] == 2
    assert len(slack.sent_messages) == 2
    assert slack.sent_messages[0]["channel"] == "#test-birthday"
    assert slack.sent_messages[1]["channel"] == "#test-birthday"


def test_first_of_month_heartbeat(monkeypatch):
    # Mock date to 2026-06-01 (1st of month)
    fake_now = pd.Timestamp("2026-06-01 10:00:00", tz="Asia/Shanghai")
    monkeypatch.setattr(pd.Timestamp, "now", lambda tz=None: fake_now)

    df = pd.DataFrame([])
    tracker, slack = create_birthday_tracker(df)

    result = tracker.run_daily(dry_run=False)
    assert result["heartbeat"] is True
    assert result["messages_sent"] == 1
    assert "A new month has begun, I am still running!" in slack.sent_messages[0]["text"]
