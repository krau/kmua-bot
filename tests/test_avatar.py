"""Avatar cache hot-path tests.

Quotes and waifu cards hit ``ChatAvatar`` on every use; a burst of cache
misses used to fan out into unbounded parallel ``get_chat`` + ``download_media``
calls (the "avatar refresh storm" that congests the Telegram session). These
tests pin the contracts that bound the storm at the call path:

- a failed refresh is remembered, and hot paths back off for
  ``avatar_refresh_retry_after`` seconds instead of retrying a dead session
  on every call;
- the backoff expires, so the avatar self-heals after the outage;
- explicit ``force_refresh()`` bypasses the backoff;
- refreshing one size does not download the other size.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Any

import pytest

from kmua.common import avatar as avatar_mod
from kmua.config import app_config


class _Photo:
    big_file_id = "big-id"
    small_file_id = "small-id"


class _ChatFull:
    def __init__(self) -> None:
        self.photo = _Photo()


class _FakeClient:
    def __init__(self) -> None:
        self.get_chat_calls = 0
        self.download_calls = 0
        self.fail = False

    async def get_chat(self, chat_id, full=False):
        self.get_chat_calls += 1
        if self.fail:
            raise TimeoutError("Request timed out")
        return _ChatFull()

    async def download_media(self, file_id, in_memory=False):
        self.download_calls += 1
        return io.BytesIO(b"avatar-bytes")


class _User:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.update_avatar_at = datetime.now() - timedelta(days=2)
        self.avatar_big_id: str | None = None


@pytest.fixture
def fake_client(monkeypatch) -> Generator[_FakeClient, Any, Any]:
    client = _FakeClient()
    monkeypatch.setattr(avatar_mod, "client", client)
    yield client
    avatar_mod._avatar_refresh_failed_at.clear()


@pytest.fixture
def fake_db(monkeypatch) -> dict[int, _User]:
    users: dict[int, _User] = {}

    async def get_user_by_id(user_id: int):
        return users.get(user_id)

    async def update_user_avatar(
        user_id: int,
        avatar_big_id: str | None = None,
        refreshed: bool = False,
        session=None,
    ):
        user = users.get(user_id)
        if user is None:
            raise ValueError(f"User with id {user_id} not found")
        user.avatar_big_id = avatar_big_id
        if refreshed:
            user.update_avatar_at = datetime.now()

    monkeypatch.setattr(avatar_mod.database, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(avatar_mod.database, "update_user_avatar", update_user_avatar)
    return users


@pytest.fixture
def avatar_cache_dir(tmp_path, monkeypatch) -> object:
    monkeypatch.setattr(app_config, "avatar_cache_dir", tmp_path)
    return tmp_path


async def test_failed_refresh_backs_off(fake_client: _FakeClient) -> None:
    fake_client.fail = True
    with pytest.raises(TimeoutError):
        await avatar_mod._get_avatar_bytes(123, force_refresh=True)
    assert fake_client.get_chat_calls == 1

    # Second call within the retry window: no network at all.
    avatar, refreshed = await avatar_mod._get_avatar_bytes(123, force_refresh=True)
    assert avatar is None and refreshed is False
    assert fake_client.get_chat_calls == 1


async def test_backoff_expires_after_retry_after(
    fake_client: _FakeClient, avatar_cache_dir
) -> None:
    fake_client.fail = True
    with pytest.raises(TimeoutError):
        await avatar_mod._get_avatar_bytes(123, force_refresh=True)

    loop = asyncio.get_running_loop()
    avatar_mod._avatar_refresh_failed_at[123] = (
        loop.time() - app_config.avatar_refresh_retry_after - 1
    )
    fake_client.fail = False

    avatar, refreshed = await avatar_mod._get_avatar_bytes(123, force_refresh=True)
    assert avatar == b"avatar-bytes" and refreshed is True
    assert fake_client.get_chat_calls == 2


async def test_force_refresh_bypasses_backoff(
    fake_client: _FakeClient, avatar_cache_dir
) -> None:
    fake_client.fail = True
    with pytest.raises(TimeoutError):
        await avatar_mod._get_avatar_bytes(123, force_refresh=True, ignore_backoff=True)
    with pytest.raises(TimeoutError):
        await avatar_mod._get_avatar_bytes(123, force_refresh=True, ignore_backoff=True)
    assert fake_client.get_chat_calls == 2


async def test_save_if_not_exists_backs_off(
    fake_client: _FakeClient, avatar_cache_dir
) -> None:
    fake_client.fail = True
    await avatar_mod.ChatAvatar(123).save_if_not_exists()
    assert fake_client.get_chat_calls == 1

    await avatar_mod.ChatAvatar(123).save_if_not_exists()
    assert fake_client.get_chat_calls == 1  # backoff, no retry


async def test_get_bytes_refreshes_only_requested_size(
    fake_client: _FakeClient,
    fake_db: dict[int, _User],
    avatar_cache_dir,
) -> None:
    fake_db[999] = _User(999)
    cache_dir = avatar_cache_dir

    avatar = await avatar_mod.ChatAvatar(999).get_bytes(big=True)
    assert avatar == b"avatar-bytes"
    assert fake_client.download_calls == 1  # only big downloaded
    assert not (cache_dir / "99" / "999_small.jpg").exists()

    # The other size is refreshed lazily on its own first use.
    small = await avatar_mod.ChatAvatar(999).get_bytes(big=False)
    assert small == b"avatar-bytes"
    assert fake_client.download_calls == 2
    assert (cache_dir / "99" / "999_small.jpg").exists()
