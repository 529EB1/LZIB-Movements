import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lzib_movements.config import Settings
from lzib_movements.database import Database


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: run this coroutine test on an event loop")


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Small dependency-free coroutine runner for isolated async unit tests."""
    if "asyncio" not in pyfuncitem.keywords:
        return None
    function = pyfuncitem.obj
    arguments = {name: pyfuncitem.funcargs[name] for name in inspect.signature(function).parameters}
    asyncio.run(function(**arguments))
    return True


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 30, 12, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "state.db")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    special = tmp_path / "special.json"
    ignored = tmp_path / "ignored.json"
    special.write_text('[{"registration":"SP-ONE","livery":"Test livery"}]')
    ignored.write_text('["IG-NORE", "SP-ONE"]')
    return Settings(
        database_path=tmp_path / "state.db",
        special_registrations_path=special,
        ignored_registrations_path=ignored,
    )
