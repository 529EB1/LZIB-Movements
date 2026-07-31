"""Bounded download and safe extraction of official VRS standing data."""

import hashlib
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from ..database import Database
from .importer import RouteDataError, import_route_directory

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024


async def update_routes(
    database: Database, url: str, *, client: httpx.AsyncClient | None = None
) -> int:
    owned = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=True)
    try:
        response = await http.get(url)
        response.raise_for_status()
        archive = response.content
        if not archive or len(archive) > MAX_ARCHIVE_BYTES:
            raise RouteDataError("route archive is empty or exceeds the size limit")
        version = response.headers.get("etag", "").strip('"') or hashlib.sha256(archive).hexdigest()
        with tempfile.TemporaryDirectory(prefix="lzib-routes-") as temporary:
            root = Path(temporary)
            _safe_extract(archive, root)
            return import_route_directory(database, root, url, version=version)
    except (httpx.HTTPError, zipfile.BadZipFile) as error:
        raise RouteDataError("route-data download or archive validation failed") from error
    finally:
        if owned:
            await http.aclose()


def _safe_extract(archive: bytes, destination: Path) -> None:
    with tempfile.NamedTemporaryFile() as handle:
        handle.write(archive)
        handle.flush()
        with zipfile.ZipFile(handle.name) as zipped:
            total = 0
            for info in zipped.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts or info.is_dir():
                    if info.is_dir():
                        continue
                    raise RouteDataError("unsafe path in route archive")
                total += info.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise RouteDataError("extracted route data exceeds the size limit")
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(info) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
