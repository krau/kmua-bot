import json
from typing import Any
from sqlalchemy import func
import sqlalchemy
from telegram import Chat
from sqlalchemy.sql import update
from kmua.dao._db import _db, commit
from kmua.models.models import ChatData, Quote, UserData, ChatConfig


def _get_stmt(chat_id: int, key: str, value: Any) -> sqlalchemy.sql.Update:
    return (
        update(ChatData)
        .where(ChatData.id == chat_id)
        .values(
            config=func.json_set(
                ChatData.config,
                key,
                value,
            )
        )
    )


def get_chat_by_id(chat_id: int) -> ChatData | None:
    return _db.query(ChatData).filter(ChatData.id == chat_id).first()


def add_chat(chat: Chat | ChatData) -> ChatData:
    """
    add chat if not exists

    :param chat: Chat or ChatData object
    :return: ChatData object
    """
    if chatdata := get_chat_by_id(chat.id):
        return chatdata
    _db.add(
        ChatData(
            id=chat.id,
            title=chat.title,
        )
    )
    commit()
    return get_chat_by_id(chat.id)


def get_chat_members(chat: Chat | ChatData) -> list[UserData]:
    _db_chat = get_chat_by_id(chat.id)
    if _db_chat is None:
        add_chat(chat)
        return []
    return _db_chat.members


def get_chat_members_id(chat: Chat | ChatData) -> list[int]:
    members = get_chat_members(chat)
    return [member.id for member in members]


def get_chat_quote_probability(chat: Chat | ChatData) -> float:
    _db_chat = get_chat_by_id(chat.id)
    if _db_chat is None:
        add_chat(chat)
        return 0.001
    return _db_chat.config.get("quote_probability", 0.001)


def update_chat_quote_probability(chat: Chat | ChatData, probability: float):
    _db_chat = get_chat_by_id(chat.id)
    if _db_chat is None:
        add_chat(chat)
        _db_chat = get_chat_by_id(chat.id)
    _db.execute(_get_stmt(chat.id, "$.quote_probability", probability))
    commit()


def get_chat_random_quote(chat: Chat | ChatData) -> Quote | None:
    return (
        _db.query(Quote)
        .filter(Quote.chat_id == chat.id)
        .order_by(func.random())
        .first()
    )


def get_chat_quotes_count(chat: Chat | ChatData) -> int:
    return _db.query(Quote).filter(Quote.chat_id == chat.id).count()


def get_chat_quotes_page(
    chat: Chat | ChatData, page: int, page_size: int
) -> list[Quote]:
    return (
        _db.query(Quote)
        .filter(Quote.chat_id == chat.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )


def get_chat_users_without_bots(chat: Chat | ChatData) -> list[UserData]:
    _db_chat = add_chat(chat)
    return [user for user in _db_chat.members if not user.is_bot]


def get_chat_users_without_bots_id(chat: Chat | ChatData) -> list[int]:
    users = get_chat_users_without_bots(chat)
    return [user.id for user in users]


def get_all_chats() -> list[ChatData]:
    return _db.query(ChatData).all()


def get_all_chats_id() -> list[int]:
    return [chat.id for chat in get_all_chats()]


def delete_chat(chat: Chat | ChatData):
    _db_chat = get_chat_by_id(chat.id)
    if _db_chat is None:
        return
    _db.delete(_db_chat)
    commit()


def get_all_chats_count() -> int:
    return _db.query(ChatData).count()


def get_chat_waifu_disabled(chat: Chat | ChatData) -> bool:
    _db_chat = add_chat(chat)
    return not _db_chat.config.get("waifu_enabled", False)


def update_chat_waifu_disabled(chat: Chat | ChatData, disabled: bool):
    add_chat(chat)
    _db.execute(_get_stmt(chat.id, "$.waifu_enabled", not disabled))
    commit()


def get_chat_delete_events_enabled(chat: Chat | ChatData) -> bool:
    _db_chat = add_chat(chat)
    return _db_chat.config.get("delete_events_enabled", False)


def update_chat_delete_events_enabled(chat: Chat | ChatData, enabled: bool):
    add_chat(chat)
    _db.execute(_get_stmt(chat.id, "$.delete_events_enabled", enabled))
    commit()


def get_chat_unpin_channel_pin_enabled(chat: Chat | ChatData) -> bool:
    _db_chat = add_chat(chat)
    return _db_chat.config.get("unpin_channel_pin_enabled", False)


def update_chat_unpin_channel_pin_enabled(chat: Chat | ChatData, enabled: bool):
    add_chat(chat)
    _db.execute(_get_stmt(chat.id, "$.unpin_channel_pin_enabled", enabled))
    commit()


def get_chat_title_permissions(chat: Chat | ChatData) -> dict:
    _db_chat = add_chat(chat)
    if _db_chat.config.get("title_permissions") is None:
        _db.execute(_get_stmt(chat.id, "$.title_permissions", "{}"))
        commit()
    if isinstance(_db_chat.config["title_permissions"], str):
        return json.loads(_db_chat.config["title_permissions"])
    elif isinstance(_db_chat.config["title_permissions"], dict):
        return _db_chat.config["title_permissions"]
    else:
        return {}


def update_chat_title_permissions(chat: Chat | ChatData, permissions: dict):
    add_chat(chat)
    _db.execute(
        _get_stmt(
            chat.id, "$.title_permissions", json.dumps(permissions, ensure_ascii=False)
        )
    )
    commit()


def get_chat_message_search_enabled(chat: Chat | ChatData) -> bool:
    _db_chat = add_chat(chat)
    return _db_chat.config.get("message_search_enabled", False)


def update_chat_message_search_enabled(chat: Chat | ChatData, enabled: bool):
    add_chat(chat)
    _db.execute(_get_stmt(chat.id, "$.message_search_enabled", enabled))
    commit()


def update_chat_greet(chat: Chat | ChatData, greet: str):
    add_chat(chat)
    _db.execute(_get_stmt(chat.id, "$.greeting", greet))
    commit()


def get_chat_config(chat: Chat | ChatData) -> ChatConfig:
    _db_chat = add_chat(chat)
    return ChatConfig.from_dict(_db_chat.config)


def update_chat_config(chat: Chat | ChatData, config: ChatConfig):
    _db_chat = add_chat(chat)
    _db_chat.config = config.to_dict()
    commit()
