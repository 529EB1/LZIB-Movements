"""Pure alert eligibility rules plus persisted duplicate/observation state."""

import hashlib
from datetime import datetime, timedelta

from ..config import Settings
from ..database import Database
from ..geometry import great_circle_distance_km
from ..models import Aircraft, AlertDecision, AlertType, Observation
from ..registration_lists import RegistrationLists


def aircraft_key(aircraft: Aircraft) -> str:
    return aircraft.icao_hex or aircraft.registration or aircraft.callsign or "unknown"


def alert_key(
    aircraft: Aircraft, alert_type: AlertType, now: datetime, cooldown_hours: float
) -> str:
    # A stable movement identity; persisted sent_at applies the precise rolling cooldown.
    parts = [
        aircraft_key(aircraft),
        aircraft.registration or "",
        aircraft.callsign or "",
        aircraft.origin_icao or "",
        aircraft.destination_icao or "",
        alert_type,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def special_arrival(
    aircraft: Aircraft,
    lists: RegistrationLists,
    settings: Settings,
    database: Database,
    now: datetime,
    distance_km: float,
) -> AlertDecision | None:
    if aircraft.on_ground is not False or aircraft.destination_icao != settings.airport_icao:
        return None
    if (
        aircraft.position_age_seconds is None
        or aircraft.position_age_seconds > settings.max_position_age_seconds
    ):
        return None
    registration = aircraft.registration
    if not registration:
        return None
    if registration in lists.special:
        alert_type = AlertType.SPECIAL_LIVERY
        reason = "Special-livery aircraft"
        livery = lists.special[registration].livery
    elif registration in lists.ignored:
        return None
    else:
        alert_type = AlertType.UNUSUAL_REGISTRATION
        reason = "Unusual aircraft registration"
        livery = None
    key = alert_key(aircraft, alert_type, now, settings.alert_cooldown_hours)
    if database.was_alerted(key, timedelta(hours=settings.alert_cooldown_hours), now):
        return None
    return AlertDecision(alert_type, aircraft, key, reason, distance_km, livery=livery)


def unusual_movement(
    aircraft: Aircraft, settings: Settings, database: Database, now: datetime
) -> AlertDecision | None:
    if aircraft.latitude is None or aircraft.longitude is None:
        return None
    distance = great_circle_distance_km(
        aircraft.latitude, aircraft.longitude, settings.airport_latitude, settings.airport_longitude
    )
    key = aircraft_key(aircraft)
    observed_at = aircraft.last_updated or now
    previous = database.previous_observation(key, observed_at)
    observation = Observation(
        key, observed_at, aircraft.altitude_ft, distance, aircraft.latitude, aircraft.longitude
    )
    is_new = database.add_observation(observation)
    if not is_new or aircraft.on_ground is not False or distance > settings.unusual_radius_km:
        return None
    altitude = aircraft.altitude_ft
    if altitude is None or altitude >= settings.unusual_max_altitude_ft:
        return None
    if (
        aircraft.position_age_seconds is None
        or aircraft.position_age_seconds > settings.max_position_age_seconds
    ):
        return None
    if (aircraft.destination_icao or "").upper() in {settings.airport_iata, settings.airport_icao}:
        return None
    if database.recently_departed(
        key, now - timedelta(minutes=settings.departure_suppression_minutes)
    ):
        return None
    descent_rate = aircraft.vertical_rate_fpm
    if descent_rate is None and previous and previous.altitude_ft is not None:
        seconds = (observed_at - previous.observed_at).total_seconds()
        if 0 < seconds <= settings.max_position_age_seconds * 2:
            descent_rate = (altitude - previous.altitude_ft) / seconds * 60
    if descent_rate is None or descent_rate > -settings.min_descent_rate_fpm:
        return None
    decreasing = previous is not None and distance < previous.distance_km
    alert_id = alert_key(aircraft, AlertType.UNUSUAL_MOVEMENT, now, settings.alert_cooldown_hours)
    if database.was_alerted(alert_id, timedelta(hours=settings.alert_cooldown_hours), now):
        return None
    confidence = "High" if aircraft.destination_icao and decreasing else "Medium"
    return AlertDecision(
        AlertType.UNUSUAL_MOVEMENT,
        aircraft,
        alert_id,
        "Unusual movement",
        distance,
        descent_rate,
        decreasing,
        confidence=confidence,
    )
