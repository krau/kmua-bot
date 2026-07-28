"""Redaction tests for the runtime configuration endpoint.

The developer panel shows what the bot is running with, and that object also holds
the bot token, the database DSN and every provider key. The approach is an
allowlist, so the test injects sentinel values and then searches the whole
serialised response for them: a leak fails here regardless of which field or
nesting level introduced it.
"""

from __future__ import annotations

import json

import pytest

from kmua.config import ProviderConfig, app_config
from kmua.webapp.sanitize import config_snapshot
from tests.webapp_helpers import api_client, bearer, make_user, set_owners

pytestmark = pytest.mark.usefixtures("initialised_db")

ADMIN_ID = 930_001

# Distinctive strings that must never reach a client.
SENTINELS = {
    "token": "SENTINEL-BOT-TOKEN-a1b2c3",
    "api_hash": "SENTINEL-API-HASH-d4e5f6",
    "db_url": "postgresql+asyncpg://user:SENTINEL-DB-PASSWORD@host/db",
    "webapp_jwt_secret": "SENTINEL-JWT-SECRET-g7h8i9",
    "redis_password": "SENTINEL-REDIS-PASSWORD-j1k2",
    "manyacg_api_key": "SENTINEL-MANYACG-KEY-l3m4",
    "btts_api_key": "SENTINEL-BTTS-KEY-n5o6",
    "infographic_api_key": "SENTINEL-INFOGRAPHIC-KEY-p7q8",
    "aniobjcut_api_key": "SENTINEL-ANIOBJCUT-KEY-r9s0",
    "agent_crawl_api_token": "SENTINEL-CRAWL-TOKEN-t1u2",
}
PROVIDER_KEY_SENTINEL = "SENTINEL-PROVIDER-KEY-v3w4"


@pytest.fixture
def secrets_loaded(monkeypatch):
    """Swap every secret for a sentinel value."""
    for field, value in SENTINELS.items():
        monkeypatch.setattr(app_config, field, value, raising=False)
    monkeypatch.setattr(
        app_config,
        "agent_providers",
        {
            "default": ProviderConfig(
                url="https://api.openai.com/v1", key=PROVIDER_KEY_SENTINEL
            )
        },
        raising=False,
    )


def all_sentinels() -> list[str]:
    return [*SENTINELS.values(), PROVIDER_KEY_SENTINEL, "SENTINEL-DB-PASSWORD"]


def test_snapshot_contains_no_sentinel_values(secrets_loaded):
    serialised = json.dumps(config_snapshot(), ensure_ascii=False)

    for sentinel in all_sentinels():
        assert sentinel not in serialised, f"{sentinel} leaked into the snapshot"


def test_snapshot_reports_which_secrets_are_configured(secrets_loaded):
    snapshot = config_snapshot()

    assert snapshot["secrets"]["token"] == "***"
    assert snapshot["secrets"]["db_url"] == "***"
    assert snapshot["agent_providers"]["default"]["key"] == "***"


def test_snapshot_distinguishes_unset_secrets(monkeypatch):
    monkeypatch.setattr(app_config, "btts_api_key", None, raising=False)
    monkeypatch.setattr(app_config, "manyacg_api_key", "", raising=False)

    snapshot = config_snapshot()

    assert snapshot["secrets"]["btts_api_key"] is None
    assert snapshot["secrets"]["manyacg_api_key"] is None


def test_snapshot_keeps_provider_endpoints_visible(secrets_loaded):
    """Endpoints are needed to debug routing; only the keys are secret."""
    snapshot = config_snapshot()

    assert snapshot["agent_providers"]["default"]["url"] == "https://api.openai.com/v1"


def test_snapshot_never_exposes_the_owner_list(secrets_loaded):
    """Owner ids are a targeting list; the count is enough for the panel."""
    snapshot = config_snapshot()

    serialised = json.dumps(snapshot)
    assert "owners" not in snapshot["groups"].get("base", {})
    assert isinstance(snapshot["owners_count"], int)
    for owner_id in app_config.owners:
        assert str(owner_id) not in serialised


def test_snapshot_is_json_serialisable(secrets_loaded):
    """Paths and other non-primitive config values must survive serialisation."""
    json.dumps(config_snapshot())


async def test_config_endpoint_contains_no_sentinel_values(secrets_loaded, monkeypatch):
    await make_user(ADMIN_ID, full_name="Snapshot Admin", global_admin=True)
    set_owners(monkeypatch, [])

    async with api_client() as client:
        response = await client.get("/api/admin/config", headers=bearer(ADMIN_ID))

    assert response.status_code == 200
    body = response.text
    for sentinel in all_sentinels():
        assert sentinel not in body, f"{sentinel} leaked through the API"


async def test_config_endpoint_requires_admin(secrets_loaded, monkeypatch):
    await make_user(930_002, full_name="Nobody")
    set_owners(monkeypatch, [])

    async with api_client() as client:
        response = await client.get("/api/admin/config", headers=bearer(930_002))

    assert response.status_code == 403
