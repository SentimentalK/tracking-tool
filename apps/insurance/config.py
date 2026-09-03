import os
from dataclasses import dataclass


@dataclass
class InsuranceConfig:
    """Configuration for Insurance Tracker."""

    company_database_id: str = os.environ.get(
        "INSURANCE_COMPANY_DB", "13e5ba9898b6807eabe1df0b766c4f89"
    )
    product_database_id: str = os.environ.get(
        "INSURANCE_PRODUCT_DB", "13d5ba9898b680fb8ed5ef4a7c83a7f3"
    )
    people_database_id: str = os.environ.get(
        "INSURANCE_PEOPLE_DB", "13e5ba9898b680098f9be842d9784943"
    )
    order_database_id: str = os.environ.get(
        "INSURANCE_ORDER_DB", "13e5ba9898b680aeae39e39c783c2ede"
    )

    slack_channel: str = os.environ.get("INSURANCE_SLACK_CHANNEL", "#保单提醒")
    slack_channel_id: str = os.environ.get("INSURANCE_SLACK_CHANNEL_ID", "C06S9557C3Y")
    slack_admin_id: str = (
        os.environ.get("INSURANCE_SLACK_ADMIN_ID")
        or os.environ.get("SLACK_ADMIN")
        or os.environ.get("slack_admin")
        or "U034H72T319"
    )
    slack_user_id: str = (
        os.environ.get("INSURANCE_SLACK_USER_ID")
        or os.environ.get("SLACK_USER")
        or os.environ.get("slack_user")
        or "U034EB7UKEZ"
    )

    timezone: str = os.environ.get("INSURANCE_TIMEZONE", "Asia/Shanghai")
