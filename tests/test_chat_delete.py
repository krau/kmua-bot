"""Chat deletion must clear user_chat_association rows first.

The database constrains user_chat_association.chat_id with RESTRICT (the
model declares CASCADE, but the constraint predates it), and the members
relationship is noload, so an ORM delete alone raises an IntegrityError on
Postgres. delete_chat clears the join rows explicitly.
"""

from __future__ import annotations

import pytest
import sqlalchemy

from kmua import database
from kmua.database.models import UserChatAssociation
from tests.webapp_helpers import join_chat, make_chat, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")


async def test_delete_chat_clears_association_rows():
    chat = await make_chat(-100_777_001)
    user = await make_user(910_001)
    await join_chat(user, chat)
    await database.add_association_in_chat(chat, user)

    assert await database.delete_chat(chat.id) is True
    assert await database.get_chat_by_id(chat.id) is None

    from kmua.database.db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        remaining = await session.scalar(
            sqlalchemy.select(sqlalchemy.func.count()).select_from(UserChatAssociation)
        )
    assert remaining == 0


async def test_delete_chat_absent_returns_false():
    assert await database.delete_chat(-100_999_999) is False
