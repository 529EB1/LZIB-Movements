import io
import zipfile
from datetime import timedelta

import httpx
import pytest

from lzib_movements.routes.downloader import update_routes
from lzib_movements.routes.importer import RouteDataError, import_route_directory
from lzib_movements.routes.matcher import RouteMatcher


def fixture_tables(root, *, archived=False):
    (root / "airports.csv").write_text("Code,Icao,Archived\nBTS,LZIB,false\nVIE,LOWW,false\n")
    (root / "routes.csv").write_text(
        "Callsign,AirportCodes,Operator,Archived\n"
        f" TST 1 ,VIE-BTS,Test Air,{str(archived).lower()}\n"
    )


def test_valid_import_join_normalization_metadata(database, tmp_path, now):
    fixture_tables(tmp_path)
    assert import_route_directory(database, tmp_path, "fixture", now=now) == 1
    route = RouteMatcher(database).match(" tst-1 ")
    assert route and route.origin_icao == "LOWW" and route.destination_icao == "LZIB"
    assert route.operator == "Test Air" and database.route_updated_at() == now


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
            archive.writestr("standing/airports.csv", "Code,Icao\nBTS,LZIB\nVIE,LOWW\n")
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
