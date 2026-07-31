"""SQLite state, request budgeting, route index, and retention."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Observation, RouteConfidence, RouteMatch

SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL);
                INSERT INTO schema_meta(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_meta);
                CREATE TABLE IF NOT EXISTS sent_alerts(
                    alert_key TEXT PRIMARY KEY, alert_type TEXT NOT NULL,
                    sent_at TEXT NOT NULL, payload_summary TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS observations(
                    id INTEGER PRIMARY KEY, aircraft_key TEXT NOT NULL,
                    observed_at TEXT NOT NULL, altitude_ft REAL, distance_km REAL NOT NULL,
                    latitude REAL NOT NULL, longitude REAL NOT NULL,
                    UNIQUE(aircraft_key, observed_at)
                );
                CREATE INDEX IF NOT EXISTS observations_aircraft_time
                    ON observations(aircraft_key, observed_at DESC);
                CREATE TABLE IF NOT EXISTS recent_departures(
                    aircraft_key TEXT PRIMARY KEY, departed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_requests(
                    provider TEXT NOT NULL, utc_day TEXT NOT NULL, request_count INTEGER NOT NULL,
                    PRIMARY KEY(provider, utc_day)
                );
                CREATE TABLE IF NOT EXISTS routes(
                    callsign TEXT PRIMARY KEY, origin_icao TEXT, destination_icao TEXT,
                    operator TEXT, exact_match INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS routes_destination ON routes(destination_icao);
                CREATE TABLE IF NOT EXISTS route_metadata(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version TEXT,
                    updated_at TEXT NOT NULL, source_url TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS photo_cache(
                    registration TEXT PRIMARY KEY, thumbnail_url TEXT, source_url TEXT,
                    photographer TEXT, expires_at TEXT NOT NULL
                );
                """
            )

    def claim_request(self, provider: str, limit: int, reserve: int, now: datetime) -> bool:
        day = now.astimezone(UTC).date().isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT request_count FROM provider_requests WHERE provider=? AND utc_day=?",
                (provider, day),
            ).fetchone()
            count = int(row[0]) if row else 0
            if count >= limit - reserve:
                return False
            db.execute(
                """INSERT INTO provider_requests(provider, utc_day, request_count) VALUES(?,?,1)
                ON CONFLICT(provider,utc_day) DO UPDATE SET request_count=request_count+1""",
                (provider, day),
            )
            return True

    def request_count(self, provider: str, now: datetime) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT request_count FROM provider_requests WHERE provider=? AND utc_day=?",
                (provider, now.astimezone(UTC).date().isoformat()),
            ).fetchone()
            return int(row[0]) if row else 0

    def was_alerted(self, key: str, cooldown: timedelta, now: datetime) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT sent_at FROM sent_alerts WHERE alert_key=?", (key,)).fetchone()
        return bool(row and datetime.fromisoformat(row[0]) > now - cooldown)

    def record_alert(self, key: str, alert_type: str, now: datetime, summary: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO sent_alerts(alert_key,alert_type,sent_at,payload_summary)
                VALUES(?,?,?,?) ON CONFLICT(alert_key) DO UPDATE SET sent_at=excluded.sent_at,
                payload_summary=excluded.payload_summary""",
                (key, alert_type, now.isoformat(), summary),
            )

    def add_observation(self, observation: Observation) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO observations
                (aircraft_key,observed_at,altitude_ft,distance_km,latitude,longitude)
                VALUES(?,?,?,?,?,?)""",
                (
                    observation.aircraft_key,
                    observation.observed_at.isoformat(),
                    observation.altitude_ft,
                    observation.distance_km,
                    observation.latitude,
                    observation.longitude,
                ),
            )
            return cursor.rowcount == 1

    def previous_observation(self, key: str, before: datetime) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT * FROM observations WHERE aircraft_key=? AND observed_at < ?
                ORDER BY observed_at DESC LIMIT 1""",
                (key, before.isoformat()),
            ).fetchone()
        if not row:
            return None
        return Observation(
            row["aircraft_key"],
            datetime.fromisoformat(row["observed_at"]),
            row["altitude_ft"],
            row["distance_km"],
            row["latitude"],
            row["longitude"],
        )

    def record_departure(self, key: str, now: datetime) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO recent_departures VALUES(?,?) ON CONFLICT(aircraft_key)
                DO UPDATE SET departed_at=excluded.departed_at""",
                (key, now.isoformat()),
            )

    def recently_departed(self, key: str, since: datetime) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT departed_at FROM recent_departures WHERE aircraft_key=?", (key,)
            ).fetchone()
        return bool(row and datetime.fromisoformat(row[0]) >= since)

    def route(self, callsign: str) -> RouteMatch | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM routes WHERE callsign=?", (callsign,)).fetchone()
        if not row:
            return None
        confidence = RouteConfidence.STRONG if row["exact_match"] else RouteConfidence.MATCH
        return RouteMatch(
            callsign, row["origin_icao"], row["destination_icao"], row["operator"], confidence
        )

    def route_updated_at(self) -> datetime | None:
        with self.connect() as db:
            row = db.execute("SELECT updated_at FROM route_metadata WHERE singleton=1").fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def cleanup(self, now: datetime) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM observations WHERE observed_at < ?",
                ((now - timedelta(hours=48)).isoformat(),),
            )
            db.execute(
                "DELETE FROM sent_alerts WHERE sent_at < ?",
                ((now - timedelta(days=30)).isoformat(),),
            )
            db.execute(
                "DELETE FROM provider_requests WHERE utc_day < ?",
                ((now - timedelta(days=14)).date().isoformat(),),
            )
            db.execute("DELETE FROM photo_cache WHERE expires_at < ?", (now.isoformat(),))
            db.execute(
                "DELETE FROM recent_departures WHERE departed_at < ?",
                ((now - timedelta(days=1)).isoformat(),),
            )
