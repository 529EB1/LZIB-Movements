"""Airplanes.live v2 REST API adapter."""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..database import Database
from ..models import Aircraft
from ..registration_lists import normalize_callsign, normalize_registration
from .base import BudgetExhausted, ProviderError, RateLimited

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.airplanes.live/v2"


class AirplanesLiveProvider:
    """Fetch one geographic response and map documented readsb fields."""

    def __init__(
        self,
        database: Database,
        daily_limit: int,
        reserve: int,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.database = database
        self.daily_limit = daily_limit
        self.reserve = reserve
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5))
        self._owns_client = client is None
        self._last_request_monotonic = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def nearby(self, latitude: float, longitude: float, radius_nm: float) -> list[Aircraft]:
        now = datetime.now(UTC)
        if not self.database.claim_request("airplanes.live", self.daily_limit, self.reserve, now):
            raise BudgetExhausted("Airplanes.live local daily request budget exhausted")
        wait = 1.0 - (time.monotonic() - self._last_request_monotonic)
        if wait > 0:
            await asyncio.sleep(wait)
        url = f"{BASE_URL}/point/{latitude:.6f}/{longitude:.6f}/{radius_nm:g}"
        try:
            self._last_request_monotonic = time.monotonic()
            response = await self.client.get(url)
        except httpx.TimeoutException as error:
            raise ProviderError("Airplanes.live request timed out") from error
        except httpx.HTTPError as error:
            raise ProviderError("Airplanes.live transport failure") from error
        if response.status_code == 429:
            raise RateLimited("Airplanes.live rate limited the request")
        if response.is_error:
            raise ProviderError(f"Airplanes.live returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError("Airplanes.live returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("ac"), list):
            raise ProviderError("Airplanes.live response does not contain an aircraft list")
        server_now = _number(payload.get("now"))
        return [_map_aircraft(item, server_now) for item in payload["ac"] if isinstance(item, dict)]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _map_aircraft(item: dict[str, Any], server_now: float | None) -> Aircraft:
    hex_code = str(item.get("hex", "")).strip().lower()
    seen_pos = _number(item.get("seen_pos"))
    seen = _number(item.get("seen"))
    age = seen_pos if seen_pos is not None else seen
    updated = None
    if server_now is not None and age is not None:
        epoch_seconds = server_now / 1000 if server_now > 100_000_000_000 else server_now
        updated = datetime.fromtimestamp(epoch_seconds, UTC) - timedelta(seconds=age)
    altitude_value = item.get("alt_baro")
    on_ground = altitude_value == "ground" if altitude_value is not None else None
    altitude = None if on_ground else _number(altitude_value)
    vertical_rate = _number(item.get("baro_rate"))
    if vertical_rate is None:
        vertical_rate = _number(item.get("geom_rate"))
    registration = normalize_registration(item.get("r"), strict=False)
    callsign = normalize_callsign(item.get("flight"))
    return Aircraft(
        icao_hex=hex_code,
        registration=registration,
        callsign=callsign,
        aircraft_type=str(item["t"]).strip().upper() if item.get("t") else None,
        category=str(item["category"]) if item.get("category") else None,
        latitude=_number(item.get("lat")),
        longitude=_number(item.get("lon")),
        barometric_altitude_ft=altitude,
        geometric_altitude_ft=_number(item.get("alt_geom")),
        ground_speed_knots=_number(item.get("gs")),
        track_degrees=_number(item.get("track")),
        vertical_rate_fpm=vertical_rate,
        on_ground=on_ground,
        position_age_seconds=age,
        last_updated=updated,
        operator=str(item["ownOp"]).strip() if item.get("ownOp") else None,
    )
