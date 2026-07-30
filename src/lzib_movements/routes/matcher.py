"""Fast callsign matching against the imported SQLite index."""

from ..database import Database
from ..models import RouteMatch
from ..registration_lists import normalize_callsign


class RouteMatcher:
    def __init__(self, database: Database) -> None:
        self.database = database

    def match(self, callsign: str | None) -> RouteMatch | None:
        normalized = normalize_callsign(callsign)
        return self.database.route(normalized) if normalized else None
