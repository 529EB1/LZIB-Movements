"""Command-line interface."""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime

from .alerts.discord import DiscordWebhook
from .config import Settings
from .database import Database
from .logging_config import configure_logging
from .models import AlertDecision, AlertType
from .monitor import Monitor
from .providers.airplanes_live import AirplanesLiveProvider
from .registration_lists import RegistrationLists
from .routes.downloader import update_routes
from .routes.importer import RouteDataError

LOGGER = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m lzib_movements")
    result.add_argument("command", nargs="?", choices=["update-routes"])
    result.add_argument("--once", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--check-config", action="store_true")
    return result


def check_config(settings: Settings, database: Database) -> list[str]:
    errors = settings.validate(require_webhooks=not settings.dry_run)
    try:
        lists = RegistrationLists.load(
            settings.special_registrations_path, settings.ignored_registrations_path
        )
        overlap = lists.special.keys() & lists.ignored
        if overlap:
            LOGGER.warning(
                "Special list takes priority for %d overlapping registration(s)", len(overlap)
            )
    except ValueError as error:
        errors.append(str(error))
    updated = database.route_updated_at()
    if updated is None:
        errors.append("route database is unavailable; run update-routes")
    elif datetime.now(UTC) - updated > settings.route_max_age:
        errors.append("route database is older than ROUTE_DATA_MAX_AGE_DAYS")
    return errors


async def async_main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    settings = Settings.from_env()
    if args.dry_run:
        settings = settings.with_dry_run(True)
    configure_logging(settings.log_level)
    database = Database(settings.database_path)
    if args.command == "update-routes":
        try:
            count = await update_routes(database, settings.route_data_url)
        except RouteDataError as error:
            LOGGER.error("Route update failed; previous valid data retained: %s", error)
            return 1
        LOGGER.info("Route update succeeded: imported %d routes", count)
        return 0
    if args.check_config:
        errors = check_config(settings, database)
        for message in errors:
            LOGGER.error("Configuration: %s", message)
        if errors:
            return 1
        LOGGER.info("Configuration is valid (webhook values present and redacted)")
        return 0
    errors = settings.validate(require_webhooks=not settings.dry_run)
    if errors:
        for message in errors:
            LOGGER.error("Configuration: %s", message)
        return 2
    provider = AirplanesLiveProvider(
        database, settings.daily_request_limit, settings.request_reserve
    )
    special = DiscordWebhook(settings.special_webhook_url) if not settings.dry_run else None
    unusual = DiscordWebhook(settings.unusual_webhook_url) if not settings.dry_run else None

    async def send(decision: AlertDecision, embed: dict[str, object]) -> None:
        webhook = unusual if decision.alert_type is AlertType.UNUSUAL_MOVEMENT else special
        if webhook is None:
            raise RuntimeError("Discord webhook is not configured")
        await webhook.send(embed)

    monitor = Monitor(settings, database, provider, send)
    try:
        if args.once:
            await monitor.scan()
        else:
            await monitor.run_forever()
    finally:
        await provider.close()
        if special:
            await special.close()
        if unusual:
            await unusual.close()
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
