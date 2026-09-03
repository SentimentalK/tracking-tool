import logging
import re
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from tracker.notion import Table
from tracker.slack import SlackClient
from .config import InsuranceConfig
from .renderer import InsuranceRenderer

logger = logging.getLogger(__name__)


class InsuranceTracker:
    """Business logic and workflow for Insurance tracking."""

    def __init__(
        self,
        config: Optional[InsuranceConfig] = None,
        notion_token: Optional[str] = None,
        slack_token: Optional[str] = None,
        slack_client: Optional[SlackClient] = None,
    ):
        self.config = config or InsuranceConfig()
        self.slack = slack_client or SlackClient(token=slack_token)
        self.renderer = InsuranceRenderer(
            user_id=self.config.slack_user_id,
            admin_id=self.config.slack_admin_id,
        )

        # Initialize Notion tables (lazy-loaded when accessed)
        self.comp = Table(self.config.company_database_id, token=notion_token)
        self.relations_cp = {
            "保险公司": {"from_table": self.comp, "lookup_column": "公司名称"},
            "备注": {"from_table": self.comp, "lookup_column": "备注"},
        }
        self.prod = Table(
            self.config.product_database_id,
            relations=self.relations_cp,
            token=notion_token,
        )
        self.ppl = Table(self.config.people_database_id, token=notion_token)
        self.relations_opp = {
            "投保人": {"from_table": self.ppl, "lookup_column": "姓名"},
            "被保险人": {"from_table": self.ppl, "lookup_column": "姓名"},
            "投保险种产品名称": {"from_table": self.prod, "lookup_column": "产品名称"},
        }
        self.odr = Table(
            self.config.order_database_id,
            relations=self.relations_opp,
            token=notion_token,
        )

    def send_reminders(self, data: pd.DataFrame) -> None:
        """Send Slack renewal reminder cards for the given order DataFrame subset."""
        if data.empty:
            return

        def _get_val(series: pd.Series, default: Any = "") -> Any:
            return series.values[0] if len(series) > 0 else default

        used_columns = {
            "投保人|姓名",
            "被保险人|姓名",
            "下次续费时间",
            "缴费倒计时",
            "保费",
            "缴费期间",
            "保单号",
            "投保险种产品名称|产品名称",
            "最晚缴费时间",
            "已缴次数",
        }
        black_list = {"保障责任", "notion_id", "slack时间戳"}

        for notion_id, row in data.iterrows():
            applicant_df = self.ppl.df[self.ppl.df["姓名"] == row["投保人|姓名"]]
            insured_df = self.ppl.df[self.ppl.df["姓名"] == row["被保险人|姓名"]]

            extra_fields = {
                k: row[k]
                for k in row.keys()
                if k not in used_columns and k not in black_list and pd.notna(row[k])
            }

            blocks = self.renderer.render_reminder_card(
                notion_id=str(notion_id),
                policy_no=row.get("保单号", ""),
                applicant_name=_get_val(applicant_df["姓名"], default=row.get("投保人|姓名", "")),
                applicant_age=_get_val(applicant_df["年龄"], default=None),
                applicant_birthday=_get_val(applicant_df["生日"], default=""),
                insured_name=_get_val(insured_df["姓名"], default=row.get("被保险人|姓名", "")),
                insured_age=_get_val(insured_df["年龄"], default=None),
                insured_birthday=_get_val(insured_df["生日"], default=""),
                product_name=row.get("投保险种产品名称|产品名称", ""),
                next_pay_date=row.get("下次续费时间", ""),
                countdown=row.get("缴费倒计时", 0),
                premium=row.get("保费", ""),
                payment_period=row.get("缴费期间", ""),
                latest_pay_date=row.get("最晚缴费时间", ""),
                extra_fields=extra_fields,
            )

            # Delete previous reminder message if it exists
            old_ts = row.get("slack时间戳")
            if pd.notna(old_ts) and str(old_ts).strip():
                try:
                    self.slack.delete_message(
                        channel=self.config.slack_channel_id, ts=str(old_ts)
                    )
                except Exception as e:
                    logger.warning(
                        "Delete previous message %s failed: %s", old_ts, e
                    )
                    self.slack.send_message(
                        channel=self.config.slack_channel,
                        text=(
                            f"<@{self.config.slack_admin_id}>, delete msg failed "
                            f"{old_ts} not found. {notion_id}, {row.get('保单号')}"
                        ),
                    )

            # Post new reminder message
            res = self.slack.send_message(
                channel=self.config.slack_channel, blocks=blocks
            )
            new_ts = float(res.get("ts", 0.0))
            self.odr.update_where_index(IS=notion_id, SET="slack时间戳", TO=new_ts)

    def run_daily(self) -> Dict[str, Any]:
        """Execute daily insurance routine: check renewals, send reminders, expire overdue."""
        df = self.odr.df[self.odr.df["状态"] == "有效保单"]
        unpaid = df[(df["缴费倒计时"] < 0) & (df["缴费倒计时"] >= -90)]
        short_period = df[df["缴费倒计时"].isin([0, 1, 8, 15])]
        invalid = df[df["缴费倒计时"] < -90]

        # Expire overdue policies beyond 90 days
        for notion_id in invalid.index:
            self.odr.update_where_index(IS=notion_id, SET="状态", TO="失效")

        # Send standard countdown reminders
        self.send_reminders(short_period)

        # Send unpaid reminders on Monday in configured timezone
        is_monday = (
            pd.Timestamp.now(self.config.timezone).tz_localize(None).weekday() == 0
        )
        if is_monday:
            self.send_reminders(unpaid)

        try:
            self.odr.writes()
        except UserWarning as e:
            logger.warning("UserWarning during odr.writes: %s", e)
            self.slack.send_message(
                channel=self.config.slack_channel,
                text=f"<@{self.config.slack_admin_id}>, {e}",
            )

        return {
            "valid_policies": len(df),
            "short_period_reminders": len(short_period),
            "unpaid_reminders": len(unpaid) if is_monday else 0,
            "expired": len(invalid),
        }

    def handle_action(
        self, raw_payload: Union[str, bytes, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Handle interactive button click (paid or destory) from Slack."""
        payload = self.slack.parse_interactive_payload(raw_payload)
        button = payload["actions"][0]["value"]
        blocks = payload.get("message", {}).get("blocks", [])
        response_url = payload.get("response_url")

        notion_id_matches = re.findall(
            r"notion_id:\s([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            str(blocks),
        )
        if not notion_id_matches:
            raise ValueError("Could not extract notion_id from interactive payload blocks")
        notion_id = notion_id_matches[0]

        # Acknowledge immediately with "working" status if response_url is available
        if response_url:
            working_blocks = self.renderer.render_updated_blocks(blocks, "working")
            self.slack.post_response(response_url, blocks=working_blocks)

        try:
            match button:
                case "paid":
                    t = self.odr.df.loc[notion_id, "下次续费时间"]
                    self.odr.df.loc[notion_id, "下次续费时间"] = (
                        pd.to_datetime(t) + pd.DateOffset(years=1)
                    ).strftime("%Y-%m-%d")

                    current = self.odr.df.loc[notion_id, "已缴次数"]
                    new_count = int(current) + 1 if pd.notna(current) else 1
                    self.odr.df.loc[notion_id, "已缴次数"] = new_count

                    period = self.odr.df.loc[notion_id, "缴费期间"]
                    if str(period).isdigit() and new_count >= int(period):
                        self.odr.update_where_index(IS=notion_id, SET="状态", TO="已缴满")

                case "destory":
                    self.odr.update_where_index(IS=notion_id, SET="状态", TO="失效")

            self.odr.df.loc[notion_id, "slack时间戳"] = None
            self.odr.writes()

            if response_url:
                ok_blocks = self.renderer.render_updated_blocks(blocks, "ok")
                self.slack.post_response(response_url, blocks=ok_blocks)

            return {"status": "ok", "action": button, "notion_id": notion_id}

        except UserWarning as e:
            logger.warning("UserWarning during action handling: %s", e)
            self.slack.send_message(
                channel=self.config.slack_channel,
                text=f"<@{self.config.slack_admin_id}>, {e}",
            )
            return {"status": "warning", "action": button, "notion_id": notion_id, "error": str(e)}

        except Exception as e:
            logger.error("Error during action handling: %s", e, exc_info=True)
            if response_url:
                failed_blocks = self.renderer.render_updated_blocks(blocks, "failed")
                self.slack.post_response(response_url, blocks=failed_blocks)
            raise


def run_daily(config: Optional[InsuranceConfig] = None) -> Dict[str, Any]:
    """Convenience functional API to run daily insurance routine."""
    tracker = InsuranceTracker(config=config)
    return tracker.run_daily()


def handle_action(
    payload: Union[str, bytes, Dict[str, Any]],
    config: Optional[InsuranceConfig] = None,
) -> Dict[str, Any]:
    """Convenience functional API to handle Slack interaction."""
    tracker = InsuranceTracker(config=config)
    return tracker.handle_action(payload)
