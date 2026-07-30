from dataclasses import replace
from datetime import timedelta

import pytest

from lzib_movements.alerts.rules import special_arrival, unusual_movement
from lzib_movements.geometry import great_circle_distance_km
from lzib_movements.models import Aircraft, AlertType, Observation, RouteConfidence
from lzib_movements.registration_lists import RegistrationLists


def arrival(settings, registration="SP-ONE", destination="LZIB", callsign="TST1"):
    return Aircraft(
        "abc123",
        registration,
        callsign,
        latitude=48.3,
        longitude=17.2,
        on_ground=False,
        position_age_seconds=5,
        destination_icao=destination,
        route_confidence=RouteConfidence.STRONG,
    )


@pytest.mark.parametrize(
    ("registration", "destination", "expected"),
    [
        ("SP-ONE", "LZIB", AlertType.SPECIAL_LIVERY),
        ("IG-NORE", "LZIB", None),
        ("OM-NEW", "LZIB", AlertType.UNUSUAL_REGISTRATION),
        (None, "LZIB", None),
        ("SP-ONE", "LOWW", None),
        ("SP-ONE", None, None),
    ],
)
def test_special_rules(database, settings, now, registration, destination, expected):
    decision = special_arrival(
        arrival(settings, registration, destination),
        RegistrationLists.load(
            settings.special_registrations_path, settings.ignored_registrations_path
        ),
        settings,
        database,
        now,
        10,
    )
    assert (decision.alert_type if decision else None) == expected


def test_special_priority_and_duplicate(database, settings, now):
    lists = RegistrationLists.load(
        settings.special_registrations_path, settings.ignored_registrations_path
    )
    first = special_arrival(arrival(settings), lists, settings, database, now, 10)
    assert first and first.livery == "Test livery"
    database.record_alert(first.alert_key, first.alert_type, now)
    assert (
        special_arrival(arrival(settings), lists, settings, database, now + timedelta(minutes=5), 9)
        is None
    )


def movement(settings, **changes):
    base = Aircraft(
        "def456",
        "OM-NEW",
        "TST2",
        latitude=settings.airport_latitude + 0.1,
        longitude=settings.airport_longitude,
        barometric_altitude_ft=7000,
        vertical_rate_fpm=-500,
        on_ground=False,
        position_age_seconds=5,
    )
    return replace(base, **changes)


def test_unknown_and_non_lzib_destinations_trigger(database, settings, now):
    assert unusual_movement(movement(settings), settings, database, now)
    other = movement(settings, icao_hex="def457", destination_icao="LOWW")
    assert unusual_movement(other, settings, database, now)


@pytest.mark.parametrize("destination", ["LZIB", "BTS"])
def test_bratislava_destination_never_unusual(database, settings, now, destination):
    assert (
        unusual_movement(movement(settings, destination_icao=destination), settings, database, now)
        is None
    )


@pytest.mark.parametrize(
    ("changes", "triggers"),
    [
        ({"barometric_altitude_ft": 7999}, True),
        ({"barometric_altitude_ft": 8000}, False),
        ({"barometric_altitude_ft": 9000}, False),
        ({"vertical_rate_fpm": 100}, False),
        ({"vertical_rate_fpm": 0}, False),
        ({"vertical_rate_fpm": -99}, False),
        ({"position_age_seconds": 121}, False),
        ({"on_ground": True}, False),
    ],
)
def test_unusual_boundaries(database, settings, now, changes, triggers):
    assert (
        bool(unusual_movement(movement(settings, **changes), settings, database, now)) is triggers
    )


def test_distance_boundary_and_outside(database, settings, now, monkeypatch):
    monkeypatch.setattr("lzib_movements.alerts.rules.great_circle_distance_km", lambda *a: 40.0)
    assert unusual_movement(movement(settings), settings, database, now)
    monkeypatch.setattr("lzib_movements.alerts.rules.great_circle_distance_km", lambda *a: 40.001)
    assert unusual_movement(movement(settings, icao_hex="outside"), settings, database, now) is None


def test_observation_descent_fallback_and_duplicate(database, settings, now):
    plane = movement(settings, vertical_rate_fpm=None)
    distance = great_circle_distance_km(
        plane.latitude, plane.longitude, settings.airport_latitude, settings.airport_longitude
    )
    database.add_observation(
        Observation(
            "def456",
            now - timedelta(seconds=60),
            7500,
            distance + 1,
            plane.latitude,
            plane.longitude,
        )
    )
    decision = unusual_movement(plane, settings, database, now)
    assert decision and decision.descent_rate_fpm == pytest.approx(-500)
    assert decision.distance_decreasing
    assert unusual_movement(plane, settings, database, now) is None


def test_recent_departure_and_restart_dedup(database, settings, now):
    database.record_departure("def456", now)
    assert unusual_movement(movement(settings), settings, database, now) is None
    other = movement(settings, icao_hex="restart")
    decision = unusual_movement(other, settings, database, now)
    assert decision
    database.record_alert(decision.alert_key, decision.alert_type, now)
    from lzib_movements.database import Database

    restarted = Database(database.path)
    later = movement(settings, icao_hex="restart", last_updated=now + timedelta(minutes=1))
    assert unusual_movement(later, settings, restarted, now + timedelta(minutes=1)) is None
