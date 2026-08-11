from __future__ import annotations

from types import SimpleNamespace

import pytest

from kmua import database
from kmua.plugins.middlewares import before
from tests.webapp_helpers import api_client, bearer, make_chat, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")

OWNER_ID = 910_000
TARGET_ID = 910_001
CHAT_ID = -100_910_001


async def test_set_user_blocked_flag():
    await make_user(TARGET_ID)

    await database.set_user_blocked(TARGET_ID, True)
    user = await database.get_user_by_id(TARGET_ID)
    assert user is not None
    assert user.is_blocked is True

    await database.set_user_blocked(TARGET_ID, False)
    user = await database.get_user_by_id(TARGET_ID)
    assert user is not None
    assert user.is_blocked is False


async def test_set_chat_blocked_flag():
    await make_chat(CHAT_ID)

    await database.set_chat_blocked(CHAT_ID, True)
    chat = await database.get_chat_by_id(CHAT_ID)
    assert chat is not None
    assert chat.is_blocked is True


def _fake_message(user_id: int, chat_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        sender_chat=None,
        from_user=SimpleNamespace(id=user_id),
        chat=SimpleNamespace(id=CHAT_ID, type=chat_type),
        text="hello",
        caption=None,
        outgoing=False,
        service=False,
        automatic_forward=False,
        sticker=None,
        game=None,
    )


async def _run_on_m(message, user_data, monkeypatch) -> bool:
    """Run the middleware; returns whether propagation was stopped."""
    stopped = {"value": False}
    message.stop_propagation = lambda: stopped.__setitem__("value", True)
    monkeypatch.setattr(before.database, "upsert_user", _async_return(user_data))
    await before.on_m(SimpleNamespace(), message)  # type: ignore[arg-type]
    return stopped["value"]


def _async_return(value):
    async def _fake(*args, **kwargs):
        return value

    return _fake


async def test_blocked_user_message_is_dropped(monkeypatch):
    user = await make_user(TARGET_ID)
    await database.set_user_blocked(TARGET_ID, True)
    user.is_blocked = True

    assert (
        await _run_on_m(_fake_message(TARGET_ID, "supergroup"), user, monkeypatch)
        is True
    )


async def test_unblocked_user_message_passes(monkeypatch):
    # Reset any state a previous test left in the shared row.
    await database.set_user_blocked(TARGET_ID, False)
    user = await make_user(TARGET_ID)
    # Private chat: no group branch below the block check runs.
    assert (
        await _run_on_m(_fake_message(TARGET_ID, "private"), user, monkeypatch) is False
    )


async def test_blocked_user_callback_is_dropped(monkeypatch):
    user = await make_user(TARGET_ID)
    await database.set_user_blocked(TARGET_ID, True)
    user.is_blocked = True

    stopped = {"value": False}
    cb = SimpleNamespace(
        from_user=SimpleNamespace(id=TARGET_ID),
        message=SimpleNamespace(chat=SimpleNamespace(id=CHAT_ID, type="supergroup")),
        data="x",
    )
    cb.stop_propagation = lambda: stopped.__setitem__("value", True)
    monkeypatch.setattr(before.database, "upsert_user", _async_return(user))
    await before.on_cb(SimpleNamespace(), cb)  # type: ignore[arg-type]
    assert stopped["value"] is True


async def test_block_api_endpoints(monkeypatch):
    from tests.webapp_helpers import set_owners

    set_owners(monkeypatch, [OWNER_ID])
    owner = await make_user(OWNER_ID)
    await make_user(TARGET_ID)
    await make_chat(CHAT_ID)

    async with api_client() as api:
        headers = bearer(owner.id)

        r = await api.post(f"/api/admin/users/{TARGET_ID}/block", headers=headers)
        assert r.status_code == 200
        user = await database.get_user_by_id(TARGET_ID)
        assert user is not None and user.is_blocked is True

        r = await api.post(f"/api/admin/users/{TARGET_ID}/unblock", headers=headers)
        assert r.status_code == 200
        user = await database.get_user_by_id(TARGET_ID)
        assert user is not None and user.is_blocked is False

        r = await api.post(f"/api/admin/chats/{CHAT_ID}/block", headers=headers)
        assert r.status_code == 200
        chat = await database.get_chat_by_id(CHAT_ID)
        assert chat is not None and chat.is_blocked is True

        r = await api.post(f"/api/admin/chats/{CHAT_ID}/unblock", headers=headers)
        assert r.status_code == 200
        chat = await database.get_chat_by_id(CHAT_ID)
        assert chat is not None and chat.is_blocked is False


async def test_block_api_requires_owner():
    # A plain user (not in owners, not a global admin) is refused.
    stranger = await make_user(TARGET_ID + 1)
    await make_user(TARGET_ID)

    async with api_client() as api:
        r = await api.post(
            f"/api/admin/users/{TARGET_ID}/block", headers=bearer(stranger.id)
        )
    assert r.status_code == 403
