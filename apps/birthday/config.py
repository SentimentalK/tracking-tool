import os
from dataclasses import dataclass


@dataclass
class BirthdayConfig:
    """Configuration for Birthday Tracker application."""

    slack_channel: str = os.environ.get("SLACK_BIRTHDAY_CHANNEL", "#生日提醒")
    people_db_id: str = os.environ.get(
        "NOTION_PEOPLE_DB_ID", "13e5ba9898b680098f9be842d9784943"
    )
    timezone: str = os.environ.get("BIRTHDAY_TIMEZONE", "Asia/Shanghai")
