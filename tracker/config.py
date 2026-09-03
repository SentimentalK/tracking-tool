import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvSecrets:
    notion_token: str
    slack_token: str


def load_env_secrets() -> EnvSecrets:
    """Load and validate required environment secrets.

    Raises:
        ValueError: If any required secret environment variable is missing or empty.
    """
    notion_token = os.environ.get("NOTION_TOKEN", "").strip()
    slack_token = os.environ.get("SLACK_TOKEN", "").strip()

    missing = []
    if not notion_token:
        missing.append("NOTION_TOKEN")
    if not slack_token:
        missing.append("SLACK_TOKEN")

    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Please set them via environment variables or secret manager."
        )

    return EnvSecrets(notion_token=notion_token, slack_token=slack_token)
