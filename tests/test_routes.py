import io
import zipfile
from datetime import timedelta

import httpx
import pytest

from lzib_movements.routes.downloader import update_routes
from lzib_movements.routes.importer import RouteDataError, import_route_directory
from lzib_movements.routes.matcher import RouteMatcher


def fixture_tables(root, *, archived=False):
    (root / "airports.csv").write_text("Code,ICAO,Archived\nBTS,LZIB,false\nVIE,LOWW,false\n")
    (root / "routes.csv").write_text(
        "Callsign,AirportCodes,Operator,Archived\n"
        f" TST 1 ,VIE-BTS,Test Air,{str(archived).lower()}\n"
    )


def test_valid_import_join_normalization_metadata(database, tmp_path, now):
    fixture_tables(tmp_path)
    assert import_route_directory(database, tmp_path, "fixture", now=now) == 1
    route = RouteMatcher(database).match(" tst-0001 ")
    assert route and route.origin_icao == "LOWW" and route.destination_icao == "LZIB"
    assert route.operator == "Test Air" and database.route_updated_at() == now


def test_official_schema_shards_and_airline_join(database, tmp_path, now):
    airports = tmp_path / "airports" / "schema-01" / "L"
    routes = tmp_path / "routes" / "schema-01" / "T"
    airlines = tmp_path / "airlines" / "schema-01"
    airports.mkdir(parents=True)
    routes.mkdir(parents=True)
    airlines.mkdir(parents=True)
    (airports / "LZ.csv").write_text(
        "Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
        "LZIB,Bratislava,LZIB,BTS,Bratislava,SK,48.17,17.21,436\n"
        "LOWW,Vienna,LOWW,VIE,Vienna,AT,48.11,16.57,600\n"
    )
    (routes / "TST-all.csv").write_text(
        "Callsign,Code,Number,AirlineCode,AirportCodes\nTST1,TST,1,TST,LOWW-LZIB\n"
    )
    (airlines / "airlines.csv").write_text(
        "Code,Name,ICAO,IATA,PositioningFlightPattern,CharterFlightPattern\n"
        "TST,Test Airline,TST,TS,,\n"
    )

    assert import_route_directory(database, tmp_path, "official-fixture", now=now) == 1
    route = RouteMatcher(database).match("TST1")
    assert route and route.origin_icao == "LOWW" and route.destination_icao == "LZIB"
    assert route.operator == "Test Airline"


@pytest.mark.parametrize("missing", ["airports.csv", "routes.csv"])
def test_missing_tables_rejected(database, tmp_path, missing):
    fixture_tables(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(RouteDataError):
        import_route_directory(database, tmp_path, "fixture")


def test_invalid_and_archived_csv_rejected(database, tmp_path):
    fixture_tables(tmp_path, archived=True)
    with pytest.raises(RouteDataError):
        import_route_directory(database, tmp_path, "fixture")
    (tmp_path / "airports.csv").write_bytes(b"\xff\xfe")
    with pytest.raises(RouteDataError):
        import_route_directory(database, tmp_path, "fixture")


def archive_bytes(unsafe=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if unsafe:
            archive.writestr("../escape", "bad")
        else:
            archive.writestr("standing/airports.csv", "Code,ICAO\nBTS,LZIB\nVIE,LOWW\n")
            archive.writestr("standing/routes.csv", "Callsign,AirportCodes\nTST1,VIE-BTS\n")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_download_import_and_failure_retains_previous(database, tmp_path):
    fixture_tables(tmp_path)
    import_route_directory(database, tmp_path, "old")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=archive_bytes(), headers={"etag": '"v2"'})
        )
    )
    assert await update_routes(database, "https://example.invalid/routes.zip", client=client) == 1
    assert database.route("TST1").destination_icao == "LZIB"
    await client.aclose()
    failed = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(RouteDataError):
        await update_routes(database, "https://example.invalid/routes.zip", client=failed)
    assert database.route("TST1") is not None
    await failed.aclose()


@pytest.mark.asyncio
async def test_unsafe_archive_rejected(database):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=archive_bytes(True)))
    )
    with pytest.raises(RouteDataError):
        await update_routes(database, "https://example.invalid/routes.zip", client=client)
    await client.aclose()


def test_route_age_tracked(database, tmp_path, now):
    fixture_tables(tmp_path)
    import_route_directory(database, tmp_path, "fixture", now=now)
    assert database.route_updated_at() + timedelta(days=7) == now + timedelta(days=7)
