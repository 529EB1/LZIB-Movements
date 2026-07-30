"""Discord embed formatting with bounded fields and cautious wording."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..models import AlertDecision, AlertType


def format_embed(decision: AlertDecision, detected_at: datetime, timezone: str) -> dict[str, Any]:
    aircraft = decision.aircraft
    unusual = decision.alert_type is AlertType.UNUSUAL_MOVEMENT
    title = (
        "Unusual Movement Alert — Bratislava" if unusual else "Special Arrival Alert — Bratislava"
    )
    description = (
        "An aircraft is descending below 8,000 feet within 40 km of Bratislava Airport. "
        "Its destination is unknown or is matched to an airport other than Bratislava. "
        "This movement is not confirmed as an arrival at LZIB."
        if unusual
        else "The destination shown below is a local route database match, "
        "not an official live flight plan."
    )
    fields: list[dict[str, Any]] = []

    def add(name: str, value: object | None) -> None:
        if value is not None and str(value).strip():
            fields.append({"name": name[:256], "value": str(value)[:1024], "inline": True})

    if not unusual:
        add("Alert reason", decision.reason)
        add("Livery name", decision.livery)
    add("Operator or airline", aircraft.operator or "Unknown operator")
    add("Aircraft type", aircraft.aircraft_type)
    add("Registration", aircraft.registration)
    add("ICAO hex", aircraft.icao_hex.upper())
    add("Callsign", aircraft.callsign)
    if unusual:
        add("Matched destination", aircraft.destination_icao or "Unknown")
        add(
            "Descent rate",
            f"{decision.descent_rate_fpm:.0f} ft/min"
            if decision.descent_rate_fpm is not None
            else None,
        )
        add("Distance decreasing", "Yes" if decision.distance_decreasing else "No / unknown")
        add("Confidence", decision.confidence)
    else:
        route = f"{aircraft.origin_icao or 'Unknown'} → {aircraft.destination_icao or 'Unknown'}"
        add("Route database match", route)
        add("Origin airport", aircraft.origin_icao)
        add("Destination airport", aircraft.destination_icao)
        add("Route confidence", aircraft.route_confidence.value)
    add(
        "Current altitude",
        f"{aircraft.altitude_ft:.0f} ft" if aircraft.altitude_ft is not None else None,
    )
    add("Distance from BTS", f"{decision.distance_km:.1f} km")
    add(
        "Ground speed",
        f"{aircraft.ground_speed_knots:.0f} kt"
        if aircraft.ground_speed_knots is not None
        else None,
    )
    add(
        "Current track",
        f"{aircraft.track_degrees:.0f}°" if aircraft.track_degrees is not None else None,
    )
    add(
        "Position age",
        f"{aircraft.position_age_seconds:.0f} s"
        if aircraft.position_age_seconds is not None
        else None,
    )
    add("Data provider", aircraft.provider)
    local = detected_at.astimezone(ZoneInfo(timezone))
    add("Detection time", local.strftime("%Y-%m-%d %H:%M:%S %Z"))
    return {
        "title": title,
        "description": description,
        "color": 0xE67E22 if unusual else 0x3498DB,
        "fields": fields[:25],
        "timestamp": detected_at.isoformat(),
    }
