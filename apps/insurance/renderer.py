from typing import Any, Dict, List, Optional
import pandas as pd


class InsuranceRenderer:
    """Renderer for Insurance Slack Block Kit messages."""

    def __init__(self, user_id: str = "U034EB7UKEZ", admin_id: str = "U034H72T319"):
        self.user_id = user_id
        self.admin_id = admin_id

        self.buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "emoji": True, "text": "已缴费"},
                "style": "primary",
                "value": "paid",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "emoji": True, "text": "保单失效"},
                "style": "danger",
                "value": "destory",
            },
        ]

        self.status_blocks: Dict[str, List[Dict[str, Any]]] = {
            "ok": [
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": ":white_check_mark: 数据同步成功"},
                }
            ],
            "working": [
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": ":pray: 数据同步中"},
                }
            ],
            "failed": [
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": ":x: 数据同步失败"},
                },
                {"type": "actions", "elements": self.buttons},
            ],
        }

    def render_reminder_card(
        self,
        notion_id: str,
        policy_no: Any,
        applicant_name: Any,
        applicant_age: Any,
        applicant_birthday: Any,
        insured_name: Any,
        insured_age: Any,
        insured_birthday: Any,
        product_name: Any,
        next_pay_date: Any,
        countdown: Any,
        premium: Any,
        payment_period: Any,
        latest_pay_date: Any,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Render Block Kit blocks for an insurance renewal reminder."""
        msg_id = f"保单号: {policy_no}\nnotion_id: {notion_id}"

        age_str = f"{int(applicant_age)}岁" if pd.notna(applicant_age) else ""
        msg_head = f"投保人: {applicant_name} ({age_str}, {applicant_birthday})"

        insured_age_str = f"{int(insured_age)}岁" if pd.notna(insured_age) else ""
        countdown_days = int(countdown) if pd.notna(countdown) else 0

        msg_body = (
            f"产品名称: {product_name}\n"
            f"此保单下次续费时间: {next_pay_date}\n"
            f"倒计时: `{countdown_days}`天\n"
            f"被保险人: {insured_name} ({insured_age_str}, {insured_birthday})\n"
            f"保费: {premium} x {payment_period}\n"
            f"最晚缴费时间: `{latest_pay_date}`\n"
        )

        if extra_fields:
            for k, v in extra_fields.items():
                msg_body += f"{k}: {v}\n"

        msg_body = msg_body.replace("2200-12-31", "终身")

        return [
            {
                "type": "context",
                "elements": [{"type": "plain_text", "text": msg_id}],
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": msg_head},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<@{self.user_id}>\n{msg_body}",
                },
            },
            {
                "type": "actions",
                "elements": self.buttons,
            },
        ]

    def render_updated_blocks(
        self, original_blocks: List[Dict[str, Any]], status: str
    ) -> List[Dict[str, Any]]:
        """Replace the action block with the corresponding status block."""
        base_blocks = original_blocks[:-1] if original_blocks else []
        replacement = self.status_blocks.get(status, [])
        return base_blocks + replacement
