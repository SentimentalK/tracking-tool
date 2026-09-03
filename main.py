import argparse
import logging
import sys

from tracker.config import load_env_secrets
from apps.insurance.workflow import run_daily as run_insurance_daily
from apps.birthday.workflow import run_daily as run_birthday_daily

logger = logging.getLogger("tracker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracking CLI Entrypoint")
    parser.add_argument(
        "--app",
        choices=["insurance", "birthday"],
        default="insurance",
        help="Target application to run (default: insurance)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform read-only execution without sending notifications",
    )
    parser.add_argument(
        "--force-unpaid",
        action="store_true",
        help="Force delivery of overdue insurance reminders regardless of weekday",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        load_env_secrets()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    if args.app == "insurance":
        logger.info(
            "Executing Insurance Daily Routine (force_unpaid=%s, dry_run=%s)...",
            args.force_unpaid,
            args.dry_run,
        )
        result = run_insurance_daily(force_unpaid=args.force_unpaid, dry_run=args.dry_run)
        logger.info("Completed Insurance Daily Tracker: %s", result)
    elif args.app == "birthday":
        logger.info("Executing Birthday Daily Routine (dry_run=%s)...", args.dry_run)
        result = run_birthday_daily(dry_run=args.dry_run)
        logger.info("Completed Birthday Daily Tracker: %s", result)


if __name__ == "__main__":
    main()
