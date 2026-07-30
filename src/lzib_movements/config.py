"""Environment-backed application configuration."""

import os
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# Slovak AIP LZIB AD 2.2 aerodrome reference point (documented in README).
DEFAULT_AIRPORT_LATITUDE = 48.170167
DEFAULT_AIRPORT_LONGITUDE = 17.212667
DEFAULT_ROUTE_DATA_URL = "https://github.com/vradarserver/standing-data/archive/refs/heads/main.zip"


def _bool(value: str) -> bool:
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    special_webhook_url: str = ""
    unusual_webhook_url: str = ""
    airport_iata: str = "BTS"
    airport_icao: str = "LZIB"
    airport_latitude: float = DEFAULT_AIRPORT_LATITUDE
    airport_longitude: float = DEFAULT_AIRPORT_LONGITUDE
    local_timezone: str = "Europe/Bratislava"
    search_radius_nm: float = 250
    poll_interval_seconds: int = 300
    daily_request_limit: int = 500
    request_reserve: int = 40
    unusual_radius_km: float = 20
    unusual_max_altitude_ft: float = 5000
    min_descent_rate_fpm: float = 100
    max_position_age_seconds: float = 120
    alert_cooldown_hours: float = 12
    departure_suppression_minutes: float = 30
    route_data_max_age_days: int = 7
    route_update_interval_hours: int = 24
    log_level: str = "INFO"
    dry_run: bool = False
    database_path: Path = Path("data/lzib_movements.db")
    special_registrations_path: Path = Path("data/special_registrations.json")
    ignored_registrations_path: Path = Path("data/ignored_registrations.json")
    route_data_url: str = DEFAULT_ROUTE_DATA_URL

    @classmethod
    def from_env(cls, *, load_local_dotenv: bool = True) -> "Settings":
        if load_local_dotenv:
            load_dotenv()
        e = os.environ
        return cls(
            special_webhook_url=e.get("SPECIAL_ARRIVALS_WEBHOOK_URL", ""),
            unusual_webhook_url=e.get("UNUSUAL_MOVEMENTS_WEBHOOK_URL", ""),
            airport_iata=e.get("AIRPORT_IATA", "BTS").upper(),
            airport_icao=e.get("AIRPORT_ICAO", "LZIB").upper(),
            airport_latitude=float(e.get("AIRPORT_LATITUDE", DEFAULT_AIRPORT_LATITUDE)),
            airport_longitude=float(e.get("AIRPORT_LONGITUDE", DEFAULT_AIRPORT_LONGITUDE)),
            local_timezone=e.get("LOCAL_TIMEZONE", "Europe/Bratislava"),
            search_radius_nm=float(e.get("AIRPLANES_LIVE_SEARCH_RADIUS_NM", 250)),
            poll_interval_seconds=int(e.get("AIRPLANES_LIVE_POLL_INTERVAL_SECONDS", 300)),
            daily_request_limit=int(e.get("AIRPLANES_LIVE_DAILY_REQUEST_LIMIT", 500)),
            request_reserve=int(e.get("AIRPLANES_LIVE_REQUEST_RESERVE", 40)),
            unusual_radius_km=float(e.get("UNUSUAL_MOVEMENT_RADIUS_KM", 20)),
            unusual_max_altitude_ft=float(e.get("UNUSUAL_MOVEMENT_MAX_ALTITUDE_FT", 5000)),
            min_descent_rate_fpm=float(e.get("UNUSUAL_MOVEMENT_MIN_DESCENT_RATE_FPM", 100)),
            max_position_age_seconds=float(e.get("MAX_POSITION_AGE_SECONDS", 120)),
            alert_cooldown_hours=float(e.get("ALERT_COOLDOWN_HOURS", 12)),
            departure_suppression_minutes=float(e.get("RECENT_DEPARTURE_SUPPRESSION_MINUTES", 30)),
            route_data_max_age_days=int(e.get("ROUTE_DATA_MAX_AGE_DAYS", 7)),
            route_update_interval_hours=int(e.get("ROUTE_UPDATE_INTERVAL_HOURS", 24)),
            log_level=e.get("LOG_LEVEL", "INFO").upper(),
            dry_run=_bool(e.get("DRY_RUN", "false")),
            database_path=Path(e.get("DATABASE_PATH", "data/lzib_movements.db")),
            special_registrations_path=Path(
                e.get("SPECIAL_REGISTRATIONS_PATH", "data/special_registrations.json")
            ),
            ignored_registrations_path=Path(
                e.get("IGNORED_REGISTRATIONS_PATH", "data/ignored_registrations.json")
            ),
            route_data_url=e.get("VRS_ROUTE_DATA_URL", DEFAULT_ROUTE_DATA_URL),
        )

    def with_dry_run(self, enabled: bool) -> "Settings":
        return replace(self, dry_run=enabled)

    @property
    def route_max_age(self) -> timedelta:
        return timedelta(days=self.route_data_max_age_days)

    def validate(self, *, require_webhooks: bool = True) -> list[str]:
        errors: list[str] = []
        if not (-90 <= self.airport_latitude <= 90 and -180 <= self.airport_longitude <= 180):
            errors.append("airport coordinates are outside valid ranges")
        try:
            ZoneInfo(self.local_timezone)
        except ZoneInfoNotFoundError:
            errors.append("LOCAL_TIMEZONE is not a recognised timezone")
        if self.search_radius_nm <= 0 or self.search_radius_nm > 250:
            errors.append("search radius must be greater than 0 and no more than 250 NM")
        if self.poll_interval_seconds < 1:
            errors.append("poll interval must be at least one second")
        if (
            self.daily_request_limit <= 0
            or not 0 <= self.request_reserve < self.daily_request_limit
        ):
            errors.append("request reserve must be non-negative and below the daily limit")
        for name, value in {
            "unusual radius": self.unusual_radius_km,
            "altitude limit": self.unusual_max_altitude_ft,
            "descent threshold": self.min_descent_rate_fpm,
            "position age": self.max_position_age_seconds,
            "cooldown": self.alert_cooldown_hours,
        }.items():
            if value <= 0:
                errors.append(f"{name} must be positive")
        if require_webhooks:
            webhook_values: dict[str, str] = {
                "SPECIAL_ARRIVALS_WEBHOOK_URL": self.special_webhook_url,
                "UNUSUAL_MOVEMENTS_WEBHOOK_URL": self.unusual_webhook_url,
            }
            for name, webhook_value in webhook_values.items():
                if not webhook_value.startswith("https://discord.com/api/webhooks/"):
                    errors.append(f"{name} is missing or invalid")
        return errors
