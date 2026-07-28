"""Group configuration endpoint tests.

The chat config is a single JSON column that the inline /config keyboard also
writes. These tests pin the two properties that keep the two writers compatible:
validation rejects out-of-range values before they reach the column, and a config
save never disturbs the separately-edited title permissions.
"""

from __future__ import annotations

import pytest

from kmua import database
from tests.webapp_helpers import (
    api_client,
    bearer,
    join_chat,
    make_chat,
    make_user,
    set_owners,
    stub_chat_member_lookup,
)

pytestmark = pytest.mark.usefixtures("initialised_db")

ADMIN_ID = 910_001
CHAT_ID = -100_910_001


def valid_config(**overrides) -> dict:
    payload = {
        "waifu_enabled": True,
        "delete_events_enabled": False,
        "unpin_channel_pin_enabled": False,
        "message_search_enabled": False,
        "quote_probability": 0.05,
        "quote_pin_message": True,
        "greeting": "Welcome ${user}",
        "ai_reply": True,
        "ai_reply_other_bots_enabled": False,
        "ai_comment": False,
        "setu_enabled": True,
        "convert_b23_enabled": True,
        "parse_artwork_enabled": True,
        "pick_bottle_enabled": True,
        "group_memory_enabled": True,
        "lang": "zh-CN",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def chat_admin(monkeypatch):
    admin = await make_user(ADMIN_ID, full_name="Config Admin")
    chat = await make_chat(CHAT_ID, title="Config Chat")
    await join_chat(admin, chat, bot_admin=True)
    set_owners(monkeypatch, [])
    stub_chat_member_lookup(monkeypatch)
    return admin, chat


async def test_saves_a_full_config_document(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(waifu_enabled=False, quote_probability=0.5),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["waifu_enabled"] is False
    assert body["quote_probability"] == 0.5

    stored = await database.get_chat_config(CHAT_ID)
    assert stored.waifu_enabled is False
    assert stored.quote_probability == 0.5


@pytest.mark.parametrize("probability", [-0.1, 1.1, 2, -1])
async def test_rejects_an_out_of_range_probability(chat_admin, probability):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(quote_probability=probability),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_rejects_an_overlong_greeting(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="x" * 1025),
        )

    assert response.status_code == 422


async def test_accepts_a_greeting_at_the_limit(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="x" * 1024),
        )

    assert response.status_code == 200


async def test_rejects_an_unknown_locale(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(lang="klingon"),
        )

    assert response.status_code == 422


async def test_rejects_unknown_fields(chat_admin):
    """Extra keys are refused so a client typo cannot silently do nothing."""
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(waifu_enable=False),
        )

    assert response.status_code == 422


async def test_blank_greeting_becomes_null(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="   "),
        )

    assert response.status_code == 200
    assert response.json()["greeting"] is None


async def test_saving_the_config_preserves_title_permissions(chat_admin):
    """The two pages edit the same JSON column; neither may clobber the other."""
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True}},
        )
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(),
        )

    assert response.status_code == 200
    assert response.json()["title_permissions"]["can_pin_messages"] is True


async def test_title_permissions_replace_the_whole_set(chat_admin):
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True, "can_invite_users": True}},
        )
        response = await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True}},
        )

    assert response.status_code == 200
    permissions = response.json()["title_permissions"]
    assert permissions["can_pin_messages"] is True
    assert permissions["can_invite_users"] is False


async def test_rejects_an_unknown_title_permission(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_launch_missiles": True}},
        )

    assert response.status_code == 422


async def test_config_read_matches_what_the_bot_sees(chat_admin):
    """The panel and the bot must agree on the stored config."""
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(ai_reply=False, lang="en"),
        )
        response = await client.get(f"/api/chats/{CHAT_ID}", headers=bearer(ADMIN_ID))

    assert response.status_code == 200
    from_api = response.json()["config"]
    from_bot = await database.get_chat_config(CHAT_ID)

    assert from_api["ai_reply"] == from_bot.ai_reply is False
    assert from_api["lang"] == from_bot.lang == "en"
