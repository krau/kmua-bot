"""Shared fixtures for the test suite.

The environment is configured *before* `kmua` is imported anywhere: the database
engine and the settings object are both built at module import time, so a later
override would come too late. pytest loads conftest first, which makes this the
only place the switch can happen.
"""

from __future__ import annotations

import asyncio
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


async def drain_trace_writes(timeout: float = 10.0) -> None:
    """Wait for the scheduled agent-run-trace writes to finish.

    The bot schedules them so they never delay a reply, which in tests means a write
    can outlive the test that triggered it: on the shared SQLite file the next test's
    writes then contend with it and fail with "database is locked" - a race the
    product does not have, because there the next write belongs to a different turn,
    seconds later.

    Only the trace tasks are waited for. Other coroutines this repo spawns sleep for
    minutes by design (auto-delete, the webapp server), so waiting for every
    background task would hang a session instead of failing one test.
    """
    from kmua.common import utils

    pending = [
        task
        for task in utils._background_tasks
        if not task.done() and task.get_name().startswith("agent-trace")
    ]
    if pending:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True), timeout=timeout
        )


@pytest.fixture(autouse=True)
async def _drain_spawned_writes() -> AsyncIterator[None]:
    yield
    await drain_trace_writes()
    # Conversation session ids are process-wide as well; dropping them keeps every
    # test's grouping independent of which tests ran before it.
    from kmua.common.memory_store import memstore

    for key in [
        key for key in memstore._data if key.startswith("agent_conversation_session:")
    ]:
        del memstore._data[key]


@pytest.fixture(scope="session")
async def initialised_db() -> AsyncIterator[None]:
    """Create the schema once for the whole session."""
    from kmua.database import db

    await db.init_db()
    yield
    await db.close_db()
