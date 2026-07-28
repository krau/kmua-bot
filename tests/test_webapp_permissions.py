"""Authorization boundaries for every writable endpoint.

The panel has three privilege tiers and they must not leak into each other. These
tests assert the negative direction - that a tier *cannot* reach past itself -
because that is the direction a refactor breaks silently.
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

OWNER_ID = 900_001
GLOBAL_ADMIN_ID = 900_002
CHAT_ADMIN_ID = 900_003
PLAIN_USER_ID = 900_004
OUTSIDER_ID = 900_005
CHAT_ID = -100_900_001
OTHER_CHAT_ID = -100_900_002


@pytest.fixture
async def world(monkeypatch):
    """A fixed cast of users and two chats, with owners pinned for the test."""
    owner = await make_user(OWNER_ID, full_name="Owner")
    global_admin = await make_user(
        GLOBAL_ADMIN_ID, full_name="Global Admin", global_admin=True
    )
    chat_admin = await make_user(CHAT_ADMIN_ID, full_name="Chat Admin")
    plain = await make_user(PLAIN_USER_ID, full_name="Plain User")
    outsider = await make_user(OUTSIDER_ID, full_name="Outsider")

    chat = await make_chat(CHAT_ID, title="Main Chat")
    other = await make_chat(OTHER_CHAT_ID, title="Other Chat")

    await join_chat(chat_admin, chat, bot_admin=True)
    await join_chat(plain, chat)
    await join_chat(outsider, other, bot_admin=True)

    set_owners(monkeypatch, [OWNER_ID])
    stub_chat_member_lookup(monkeypatch)

    return {
        "owner": owner,
        "global_admin": global_admin,
        "chat_admin": chat_admin,
        "plain": plain,
        "outsider": outsider,
        "chat": chat,
        "other": other,
    }


async def test_unauthenticated_requests_are_rejected(world):
    async with api_client() as client:
        for method, path in (
            ("get", "/api/me"),
            ("get", "/api/me/gifts/catalog"),
            ("get", "/api/admin/stats"),
            ("get", f"/api/chats/{CHAT_ID}"),
        ):
            response = await getattr(client, method)(path)
            assert response.status_code == 401
            assert response.json()["code"] == "TOKEN_MISSING"


async def test_plain_user_cannot_reach_the_developer_panel(world):
    async with api_client() as client:
        response = await client.get("/api/admin/stats", headers=bearer(PLAIN_USER_ID))

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"


async def test_global_admin_can_read_the_developer_panel(world):
    async with api_client() as client:
        response = await client.get("/api/admin/stats", headers=bearer(GLOBAL_ADMIN_ID))

    assert response.status_code == 200
    assert "users" in response.json()


async def test_global_admin_cannot_reload_config(world):
    """Config reload is owner-only: it can swap AI providers and cost tuning."""
    async with api_client() as client:
        response = await client.post(
            "/api/admin/config/reload", headers=bearer(GLOBAL_ADMIN_ID)
        )

    assert response.status_code == 403
    assert response.json()["code"] == "OWNER_REQUIRED"


async def test_global_admin_cannot_make_the_bot_leave_a_chat(world):
    async with api_client() as client:
        response = await client.post(
            f"/api/admin/chats/{CHAT_ID}/leave", headers=bearer(GLOBAL_ADMIN_ID)
        )

    assert response.status_code == 403
    assert response.json()["code"] == "OWNER_REQUIRED"


async def test_global_admin_cannot_edit_an_owner_record(world):
    """Horizontal escalation: a global admin must not touch an owner's row."""
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{OWNER_ID}",
            headers=bearer(GLOBAL_ADMIN_ID),
            json={"full_name": "Hijacked"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "OWNER_REQUIRED"
    owner = await database.get_user_by_id(OWNER_ID)
    assert owner is not None and owner.full_name == "Owner"


async def test_global_admin_cannot_grant_admin_rights(world):
    """Vertical escalation: only an owner may change the admin roster."""
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{PLAIN_USER_ID}",
            headers=bearer(GLOBAL_ADMIN_ID),
            json={"is_bot_global_admin": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == []
    assert body["skipped"] == [
        {"field": "is_bot_global_admin", "reason": "OWNER_REQUIRED"}
    ]
    target = await database.get_user_by_id(PLAIN_USER_ID)
    assert target is not None and not target.is_bot_global_admin


async def test_chat_admin_cannot_manage_a_different_chat(world):
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{OTHER_CHAT_ID}", headers=bearer(CHAT_ADMIN_ID)
        )

    assert response.status_code == 403
    assert response.json()["code"] == "CHAT_ADMIN_REQUIRED"


async def test_plain_member_cannot_manage_their_own_chat(world):
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}", headers=bearer(PLAIN_USER_ID)
        )

    assert response.status_code == 403
    assert response.json()["code"] == "CHAT_ADMIN_REQUIRED"


async def test_chat_admin_can_read_their_chat(world):
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}", headers=bearer(CHAT_ADMIN_ID)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == CHAT_ID
    assert body["can_manage"] is True


async def test_owner_manages_every_chat_without_membership(world):
    """Owners never joined these chats, and still manage them."""
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{OTHER_CHAT_ID}", headers=bearer(OWNER_ID)
        )

    assert response.status_code == 200


async def test_private_chat_ids_are_not_reachable_through_the_chat_routes(world):
    """A non-negative id is a user or private chat, never a manageable group."""
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{PLAIN_USER_ID}", headers=bearer(OWNER_ID)
        )

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


async def test_a_user_cannot_delete_another_users_quote(world):
    chat = world["chat"]
    victim = world["plain"]
    author = world["chat_admin"]
    link = "https://t.me/c/900001/42"
    await database.add_quote(
        chat=chat, user=victim, qer=author, link=link, message_id=42, text="mine"
    )

    async with api_client() as client:
        response = await client.delete(
            f"/api/me/quotes/{link}", headers=bearer(CHAT_ADMIN_ID)
        )

    assert response.status_code == 404
    assert await database.get_quote_by_link(link) is not None


async def test_a_chat_admin_cannot_delete_a_quote_from_another_chat(world):
    other = world["other"]
    author = world["outsider"]
    link = "https://t.me/c/900002/7"
    await database.add_quote(
        chat=other, user=author, qer=author, link=link, message_id=7, text="elsewhere"
    )

    async with api_client() as client:
        response = await client.delete(
            f"/api/chats/{CHAT_ID}/quotes/{link}", headers=bearer(CHAT_ADMIN_ID)
        )

    assert response.status_code == 404
    assert await database.get_quote_by_link(link) is not None


async def test_a_user_can_delete_their_own_quote(world):
    chat = world["chat"]
    author = world["plain"]
    link = "https://t.me/c/900001/99"
    await database.add_quote(
        chat=chat, user=author, qer=author, link=link, message_id=99, text="bye"
    )

    async with api_client() as client:
        response = await client.delete(
            f"/api/me/quotes/{link}", headers=bearer(PLAIN_USER_ID)
        )

    assert response.status_code == 204
    assert await database.get_quote_by_link(link) is None


async def test_a_deleted_account_cannot_use_an_old_token(world):
    """A valid signature over a vanished user must not authenticate."""
    async with api_client() as client:
        response = await client.get("/api/me", headers=bearer(999_999_999))

    assert response.status_code == 401
    assert response.json()["code"] == "USER_NOT_FOUND"
