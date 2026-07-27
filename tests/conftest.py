"""Shared fixtures for the test suite.

The environment is configured *before* `kmua` is imported anywhere: the database
engine and the settings object are both built at module import time, so a later
override would come too late. pytest loads conftest first, which makes this the
only place the switch can happen.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

# A throwaway sqlite file per session, so tests never touch data/kmua.db.
_TMP_DIR = tempfile.mkdtemp(prefix="kmua-tests-")
_DB_PATH = Path(_TMP_DIR) / "test.db"

os.environ.setdefault("KMUA_DB_URL", f"sqlite+aiosqlite:///{_DB_PATH}")
os.environ.setdefault("KMUA_TOKEN", "123456:test-bot-token-for-unit-tests")
os.environ.setdefault("KMUA_AUTOMIGRATE", "false")
os.environ.setdefault("KMUA_LOOP_MONITOR_ENABLED", "false")
os.environ.setdefault("KMUA_SESSION_HEALTH_ENABLED", "false")
os.environ.setdefault("KMUA_WEBAPP", "true")
os.environ.setdefault("KMUA_WEBAPP_URL", "https://panel.example.test")
os.environ.setdefault("KMUA_LOG_LEVEL", "CRITICAL")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def tmp_db_path() -> Path:
    return _DB_PATH


@pytest.fixture(autouse=True, scope="session")
def _quiet_logs() -> Iterator[None]:
    """Silence loguru so assertion output stays readable."""
    from kmua.logger import logger

    logger.remove()
    yield


@pytest.fixture(scope="session")
async def initialised_db() -> AsyncIterator[None]:
    """Create the schema once for the whole session."""
    from kmua.database import db

    await db.init_db()
    yield
    await db.close_db()
