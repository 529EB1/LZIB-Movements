"""Validated standing-data rows."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportedRoute:
    callsign: str
    origin_icao: str | None
    destination_icao: str | None
    operator: str | None
