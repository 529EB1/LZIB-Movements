"""Validate VRS standing-data CSV files and atomically replace the route index."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from ..database import Database
from ..registration_lists import normalize_callsign


class RouteDataError(ValueError):
    """Standing data is missing, malformed, or unsafe."""


def _locate(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise RouteDataError(f"required table {name} was not found exactly once")
    return matches[0]


def _table_files(root: Path, table: str) -> list[Path]:
    """Find either a legacy aggregate fixture or the official schema-01 shards."""
    aggregate = [path for path in root.rglob(f"{table}.csv") if path.is_file()]
    schema_root = next((path for path in root.rglob(f"{table}/schema-01") if path.is_dir()), None)
    if schema_root is not None:
        files = sorted(path for path in schema_root.rglob("*.csv") if path.is_file())
        if files:
            return files
    if len(aggregate) == 1:
        return aggregate
    raise RouteDataError(f"required table {table} was not found in a supported layout")


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise RouteDataError(f"{path.name} has no CSV header")
            return [{str(k).strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    except (OSError, UnicodeError, csv.Error) as error:
        raise RouteDataError(f"cannot parse {path.name}") from error


def _validated_rows(paths: list[Path], required: set[str], table: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        file_rows = _rows(path)
        if file_rows:
            missing = required - file_rows[0].keys()
            if missing:
                raise RouteDataError(
                    f"{table} file {path.name} is missing columns: {', '.join(sorted(missing))}"
                )
        rows.extend(file_rows)
    return rows


def import_route_directory(
    database: Database,
    root: Path,
    source_url: str,
    *,
    version: str | None = None,
    now: datetime | None = None,
) -> int:
    """Import documented airports/routes tables in one transaction.

    VRS standing-data field casing has varied; aliases are explicit rather than guessed
    positional columns. AirportCodes routes use origin-destination ICAO pairs.
    """
    airports_rows = _validated_rows(_table_files(root, "airports"), {"Code", "ICAO"}, "airports")
    route_rows = _validated_rows(
        _table_files(root, "routes"), {"Callsign", "AirportCodes"}, "routes"
    )
    airline_names: dict[str, str] = {}
    airline_files = [
        path for path in root.rglob("airlines/schema-01/airlines.csv") if path.is_file()
    ]
    if len(airline_files) == 1:
        for row in _validated_rows(airline_files, {"Code", "Name"}, "airlines"):
            code, name = _get(row, "Code"), _get(row, "Name")
            if code and name:
                airline_names[code.upper()] = name
    airport_map: dict[str, str] = {}
    for row in airports_rows:
        code = _get(row, "Code", "code", "Iata", "iata")
        icao = _get(row, "Icao", "ICAO", "icao")
        if code and icao and not _archived(row):
            airport_map[code.upper()] = icao.upper()
            airport_map[icao.upper()] = icao.upper()
    if not airport_map:
        raise RouteDataError("airports.csv contains no usable airport records")
    imported: dict[str, tuple[str | None, str | None, str | None]] = {}
    for row in route_rows:
        if _archived(row):
            continue
        callsign = normalize_callsign(_get(row, "Callsign", "callsign"))
        airport_codes = _get(row, "AirportCodes", "airport_codes", "Route", "route")
        if not callsign or not airport_codes:
            continue
        codes = [code.strip().upper() for code in airport_codes.replace("-", " ").split() if code]
        if len(codes) < 2:
            continue
        origin, destination = airport_map.get(codes[0]), airport_map.get(codes[-1])
        if not origin or not destination:
            continue
        airline_code = _get(row, "AirlineCode", "airline_code").upper()
        operator = airline_names.get(airline_code) or _get(row, "Operator", "operator") or None
        imported[callsign] = (origin, destination, operator)
    if not imported:
        raise RouteDataError("routes.csv contains no usable joined routes")
    timestamp = (now or datetime.now(UTC)).isoformat()
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TEMP TABLE new_routes AS SELECT * FROM routes WHERE 0")
        db.executemany(
            "INSERT INTO new_routes"
            "(callsign,origin_icao,destination_icao,operator,exact_match) VALUES(?,?,?,?,1)",
            [(callsign, *values) for callsign, values in imported.items()],
        )
        db.execute("DELETE FROM routes")
        db.execute("INSERT INTO routes SELECT * FROM new_routes")
        db.execute("DROP TABLE new_routes")
        db.execute(
            """INSERT INTO route_metadata(singleton,version,updated_at,source_url) VALUES(1,?,?,?)
            ON CONFLICT(singleton) DO UPDATE SET version=excluded.version,
            updated_at=excluded.updated_at,source_url=excluded.source_url""",
            (version, timestamp, source_url),
        )
    return len(imported)


def _get(row: dict[str, str], *names: str) -> str:
    return next((row[name] for name in names if row.get(name)), "")


def _archived(row: dict[str, str]) -> bool:
    value = _get(row, "IsArchived", "Archived", "Deleted", "is_archived").lower()
    return value in {"1", "true", "yes", "y"}
