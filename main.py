import logging
import sys

from tracker.config import load_env_secrets
from apps.insurance.workflow import run_daily

logger = logging.getLogger("tracker")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        load_env_secrets()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    logger.info("Starting Insurance Daily Tracker routine...")
    result = run_daily()
    logger.info("Completed Insurance Daily Tracker: %s", result)


if __name__ == "__main__":
    main()
