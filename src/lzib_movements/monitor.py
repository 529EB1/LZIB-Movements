"""One-response monitoring orchestration for both alert systems."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .alerts.formatter import format_embed
from .alerts.rules import aircraft_key, special_arrival, unusual_movement
from .config import Settings
from .database import Database
from .geometry import great_circle_distance_km
from .models import AlertDecision
from .providers.base import AircraftProvider, ProviderError
from .registration_lists import RegistrationLists
from .routes.matcher import RouteMatcher

LOGGER = logging.getLogger(__name__)
SendFunction = Callable[[AlertDecision, dict[str, object]], Awaitable[None]]


class Monitor:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        provider: AircraftProvider,
        sender: SendFunction,
    ) -> None:
        self.settings = settings
        self.database = database
        self.provider = provider
        self.sender = sender
        self.matcher = RouteMatcher(database)

    async def scan(self, *, now: datetime | None = None) -> list[AlertDecision]:
        detected_at = now or datetime.now(UTC)
        try:
            aircraft_list = await self.provider.nearby(
                self.settings.airport_latitude,
                self.settings.airport_longitude,
                self.settings.search_radius_nm,
            )
        except ProviderError as error:
            LOGGER.warning("Live aircraft scan unavailable: %s", error)
            return []
        lists = RegistrationLists.load(
            self.settings.special_registrations_path, self.settings.ignored_registrations_path
        )
        decisions: list[AlertDecision] = []
        for original in aircraft_list:
            aircraft = original.with_route(self.matcher.match(original.callsign))
            if aircraft.latitude is None or aircraft.longitude is None:
                continue
            distance = great_circle_distance_km(
                aircraft.latitude,
                aircraft.longitude,
                self.settings.airport_latitude,
                self.settings.airport_longitude,
            )
            if (
                aircraft.origin_icao == self.settings.airport_icao
                and aircraft.on_ground is False
                and distance <= 10
            ):
                self.database.record_departure(aircraft_key(aircraft), detected_at)
            special = special_arrival(
                aircraft, lists, self.settings, self.database, detected_at, distance
            )
            unusual = unusual_movement(aircraft, self.settings, self.database, detected_at)
            for decision in (special, unusual):
                if decision is None:
                    continue
                embed = format_embed(decision, detected_at, self.settings.local_timezone)
                if self.settings.dry_run:
                    LOGGER.info(
                        "Dry run: would send %s for %s", decision.alert_type, aircraft_key(aircraft)
                    )
                else:
                    try:
                        await self.sender(decision, embed)
                    except RuntimeError as error:
                        LOGGER.error("Alert delivery failed: %s", error)
                        continue
                self.database.record_alert(
                    decision.alert_key, decision.alert_type, detected_at, decision.reason
                )
                decisions.append(decision)
        self.database.cleanup(detected_at)
        return decisions

    async def run_forever(self) -> None:
        while True:
            await self.scan()
            await asyncio.sleep(self.settings.poll_interval_seconds)
