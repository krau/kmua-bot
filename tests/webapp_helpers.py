"""Shared helpers for the API integration tests.

Each test drives the real ASGI app over `httpx.ASGITransport`, so routing,
dependency injection, validation and error handling are all exercised - only the
network is skipped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from kmua import database
from kmua.database.models import ChatData, UserData
from kmua.webapp import create_app
from kmua.webapp.auth import issue_token


@asynccontextmanager
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client wired straight to the panel app."""
    app = create_app(panel_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://panel.test"
    ) as client:
        yield client


def bearer(user_id: int) -> dict[str, str]:
    token, _ = issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    user_id: int,
    *,
    full_name: str = "Test User",
    username: str | None = None,
    global_admin: bool = False,
) -> UserData:
    """Insert or update a user row directly, bypassing Telegram."""
    from kmua.database.db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        async with session.begin():
            user = await session.get(UserData, user_id)
            if user is None:
                user = UserData(
                    id=user_id,
                    full_name=full_name,
                    username=username,
                    is_bot=False,
                    is_real_user=True,
                )
                session.add(user)
            else:
                user.full_name = full_name
                user.username = username
            user.is_bot_global_admin = global_admin
    refreshed = await database.get_user_by_id(user_id)
    assert refreshed is not None
    return refreshed


async def make_chat(
    chat_id: int, *, title: str = "Test Chat", username: str | None = None
) -> ChatData:
    from kmua.database.db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        async with session.begin():
            chat = await session.get(ChatData, chat_id)
            if chat is None:
                chat = ChatData(id=chat_id, title=title, username=username)
                session.add(chat)
            else:
                chat.title = title
                chat.username = username
    refreshed = await database.get_chat_by_id(chat_id)
    assert refreshed is not None
    return refreshed


async def join_chat(user: UserData, chat: ChatData, *, bot_admin: bool = False) -> None:
    """Record membership, optionally flagged as a bot admin."""
    await database.add_association_in_chat(chat, user, None)
    if bot_admin:
        await database.set_association_bot_admin(user.id, chat.id, True)


def set_owners(monkeypatch, owner_ids: list[int]) -> None:
    """Point `app_config.owners` at the given ids for one test."""
    from kmua.config import app_config

    monkeypatch.setattr(app_config, "owners", owner_ids, raising=False)


def stub_chat_member_lookup(monkeypatch, status: str = "member") -> None:
    """Answer `client.get_chat_member` without a Telegram connection.

    `can_user_manage_bot_in_chat` falls through to Telegram for members whose
    stored `is_bot_admin` flag is false, to catch group owners and admins with
    can_promote_members. Tests have no session, so that call is stubbed - the
    stored flag becomes the whole truth, which is what the fixtures set up.
    """
    from pyrogram.enums import ChatMemberStatus

    from kmua.common import tgmethod

    resolved = ChatMemberStatus(status)

    class _StubMember:
        def __init__(self) -> None:
            self.status = resolved
            self.privileges = None

    async def _get_chat_member(chat_id, user_id, *args, **kwargs):
        return _StubMember()

    monkeypatch.setattr(
        tgmethod.client, "get_chat_member", _get_chat_member, raising=False
    )
