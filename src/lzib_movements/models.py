"""Provider-independent domain models."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class RouteConfidence(StrEnum):
    STRONG = "Strong route database match"
    MATCH = "Route database match"
    WEAK = "Weak route database match"
    UNKNOWN = "Destination unknown"


class AlertType(StrEnum):
    SPECIAL_LIVERY = "special_livery"
    UNUSUAL_REGISTRATION = "unusual_registration"
    UNUSUAL_MOVEMENT = "unusual_movement"


@dataclass(frozen=True, slots=True)
class Aircraft:
    icao_hex: str
    registration: str | None = None
    callsign: str | None = None
    aircraft_type: str | None = None
    category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    barometric_altitude_ft: float | None = None
    geometric_altitude_ft: float | None = None
    ground_speed_knots: float | None = None
    track_degrees: float | None = None
    vertical_rate_fpm: float | None = None
    on_ground: bool | None = None
    position_age_seconds: float | None = None
    last_updated: datetime | None = None
    provider: str = "Airplanes.live"
    origin_icao: str | None = None
    destination_icao: str | None = None
    route_confidence: RouteConfidence = RouteConfidence.UNKNOWN
    operator: str | None = None

    @property
    def altitude_ft(self) -> float | None:
        return self.barometric_altitude_ft or self.geometric_altitude_ft

    def with_route(self, route: "RouteMatch | None") -> "Aircraft":
        if route is None:
            return self
        return replace(
            self,
            origin_icao=route.origin_icao,
            destination_icao=route.destination_icao,
            route_confidence=route.confidence,
            operator=self.operator or route.operator,
        )


@dataclass(frozen=True, slots=True)
class RouteMatch:
    callsign: str
    origin_icao: str | None
    destination_icao: str | None
    operator: str | None = None
    confidence: RouteConfidence = RouteConfidence.MATCH


@dataclass(frozen=True, slots=True)
class Observation:
    aircraft_key: str
    observed_at: datetime
    altitude_ft: float | None
    distance_km: float
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class AlertDecision:
    alert_type: AlertType
    aircraft: Aircraft
    alert_key: str
    reason: str
    distance_km: float
    descent_rate_fpm: float | None = None
    distance_decreasing: bool | None = None
    livery: str | None = None
    confidence: str | None = None
