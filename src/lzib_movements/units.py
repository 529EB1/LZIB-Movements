"""Explicit aviation unit conversions."""

NM_TO_KM = 1.852
FT_TO_M = 0.3048
KNOT_TO_MPS = 0.514444


def nautical_miles_to_kilometres(value: float) -> float:
    return value * NM_TO_KM


def kilometres_to_nautical_miles(value: float) -> float:
    return value / NM_TO_KM


def feet_to_metres(value: float) -> float:
    return value * FT_TO_M


def metres_to_feet(value: float) -> float:
    return value / FT_TO_M


def knots_to_metres_per_second(value: float) -> float:
    return value * KNOT_TO_MPS
