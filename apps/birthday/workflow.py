import datetime
import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from tracker.notion import Table
from tracker.slack import SlackClient
from .config import BirthdayConfig

logger = logging.getLogger(__name__)


class BirthdayTracker:
    """Business logic and workflow for Birthday tracking."""

    def __init__(
        self,
        config: Optional[BirthdayConfig] = None,
        notion_token: Optional[str] = None,
        slack_token: Optional[str] = None,
        slack_client: Optional[SlackClient] = None,
        people_table: Optional[Table] = None,
    ):
        self.config = config or BirthdayConfig()
        self.slack = slack_client or SlackClient(token=slack_token)
        self.people_table = people_table or Table(
            self.config.people_db_id, token=notion_token
        )

    def calculate_occurrences(
        self, today: datetime.date, df: pd.DataFrame
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Calculate next birthday occurrence and match today and 10-day advance."""
        on_the_day: List[Dict[str, Any]] = []
        in_advance: List[Dict[str, Any]] = []

        if df is None or df.empty or "姓名" not in df.columns or "生日" not in df.columns:
            return {"on_the_day": on_the_day, "in_advance": in_advance}

        for idx, row in df.iterrows():
            name = row.get("姓名")
            if pd.isna(name) or not str(name).strip():
                continue
            name = str(name).strip()

            relation = row.get("亲属关系")
            if pd.notna(relation) and str(relation).strip():
                display_name = f"{name} ({str(relation).strip()})"
            else:
                display_name = name

            raw_bday = row.get("生日")
            if pd.isna(raw_bday) or not str(raw_bday).strip():
                continue

            try:
                parsed_date = pd.to_datetime(raw_bday).date()
            except Exception as e:
                logger.debug("Skipping invalid birthday date '%s' for %s: %s", raw_bday, name, e)
                continue

            b_month = parsed_date.month
            b_day = parsed_date.day
            b_year = None if parsed_date.year <= 1900 else parsed_date.year

            # Compute next occurrence (handling Feb 29 non-leap year fallback to Feb 28)
            try:
                occ = datetime.date(today.year, b_month, b_day)
            except ValueError:
                occ = datetime.date(today.year, 2, 28)

            if occ < today:
                try:
                    occ = datetime.date(today.year + 1, b_month, b_day)
                except ValueError:
                    occ = datetime.date(today.year + 1, 2, 28)

            days_until = (occ - today).days
            turning_age = (occ.year - b_year) if b_year else None

            if days_until == 0:
                on_the_day.append({"name": display_name, "turning_age": turning_age})
            elif days_until == 10:
                in_advance.append({"name": display_name, "turning_age": turning_age})

        # Sort entries: with age first sorted numerically, then alphabetical
        on_the_day.sort(key=lambda x: (x["turning_age"] is None, x["turning_age"] or 0, x["name"]))
        in_advance.sort(key=lambda x: (x["turning_age"] is None, x["turning_age"] or 0, x["name"]))

        return {"on_the_day": on_the_day, "in_advance": in_advance}

    def render_advance_message(self, in_advance: List[Dict[str, Any]]) -> str:
        """Render 10-day advance notice message."""
        msg = "🎂Birthday Notification🎂\n"
        for item in in_advance:
            name = item["name"]
            age = item["turning_age"]
            if age:
                msg += f"{name} has 10 days until {age}'s birthday 🧁\n"
            else:
                msg += f"{name} has 10 days until birthday 🧁\n"
        msg += "Don't forget to buy gifts 🎈"
        return msg

    def render_on_the_day_message(self, on_the_day: List[Dict[str, Any]]) -> str:
        """Render on-the-day birthday message."""
        msg = "🎂Birthday Notification🎂\n"
        for item in on_the_day:
            name = item["name"]
            age = item["turning_age"]
            if age:
                msg += f"Today is {name}'s birthday, turns {age} years old 🧁\n"
            else:
                msg += f"Today is {name}'s birthday! 🧁\n"
        msg += "Go and send your blessings! 🎈"
        return msg

    def run_daily(self, dry_run: bool = False) -> Dict[str, Any]:
        """Execute daily birthday reminder routine."""
        today = pd.Timestamp.now(self.config.timezone).date()
        logger.info(
            "Starting Birthday Daily routine for %s (timezone=%s, dry_run=%s)...",
            today,
            self.config.timezone,
            dry_run,
        )

        occurrences = self.calculate_occurrences(today, self.people_table.df)
        on_the_day = occurrences["on_the_day"]
        in_advance = occurrences["in_advance"]
        is_first_of_month = (today.day == 1)

        messages_to_send: List[str] = []
        if in_advance:
            messages_to_send.append(self.render_advance_message(in_advance))
        if on_the_day:
            messages_to_send.append(self.render_on_the_day_message(on_the_day))
        if is_first_of_month:
            messages_to_send.append("A new month has begun, I am still running!")

        sent_count = 0
        if dry_run:
            logger.info(
                "[DRY-RUN] Prepared %d messages for channel %s:",
                len(messages_to_send),
                self.config.slack_channel,
            )
            for m in messages_to_send:
                logger.info("[DRY-RUN MESSAGE]\n%s", m)
        else:
            for m in messages_to_send:
                logger.info("Sending message to %s:\n%s", self.config.slack_channel, m)
                self.slack.send_message(channel=self.config.slack_channel, text=m)
                sent_count += 1

        result = {
            "date": str(today),
            "birthdays_today": on_the_day,
            "birthdays_in_10_days": in_advance,
            "heartbeat": is_first_of_month,
            "messages_sent": sent_count,
            "dry_run": dry_run,
        }
        logger.info("Completed Birthday Daily routine: %s", result)
        return result


def run_daily(
    config: Optional[BirthdayConfig] = None, dry_run: bool = False
) -> Dict[str, Any]:
    """Convenience functional API to run daily birthday routine."""
    tracker = BirthdayTracker(config=config)
    return tracker.run_daily(dry_run=dry_run)
