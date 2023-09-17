from telegram import Chat

from ..models.models import ChatData, Quote, UserData
from .db import db, commit


def get_chat_by_id(chat_id: int) -> ChatData | None:
    return db.query(ChatData).filter(ChatData.id == chat_id).first()


def add_chat(chat: Chat | ChatData) -> ChatData:
    """
    add chat if not exists

    :param chat: Chat or ChatData object
    :return: ChatData object
    """
    if chatdata := get_chat_by_id(chat.id):
        return chatdata
    db.add(
        ChatData(
            id=chat.id,
            title=chat.title,
        )
    )
    commit()
    return get_chat_by_id(chat.id)


def get_chat_members(chat: Chat | ChatData) -> list[UserData]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return db_chat.members


def get_chat_members_id(chat: Chat | ChatData) -> list[int]:
    members = get_chat_members(chat)
    return [member.id for member in members]


def get_chat_quote_probability(chat: Chat | ChatData) -> float:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return 0.001
    return db_chat.quote_probability


def update_chat_quote_probability(chat: Chat | ChatData, probability: float):
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        db_chat = get_chat_by_id(chat.id)
    db_chat.quote_probability = probability
    commit()


def get_chat_quotes(chat: Chat | ChatData) -> list[Quote]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return db_chat.quotes


def get_chat_quotes_count(chat: Chat | ChatData) -> int:
    return len(get_chat_quotes(chat))


def get_chat_quotes_page(
    chat: Chat | ChatData, page: int, page_size: int
) -> list[Quote]:
    return get_chat_quotes(chat)[(page - 1) * page_size : page * page_size]


def get_chat_quotes_message_id(chat: Chat | ChatData) -> list[int]:
    quotes = get_chat_quotes(chat)
    return [quote.message_id for quote in quotes]


def get_chat_bots(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中的 bot
    """
    db_chat = add_chat(chat)
    return [user for user in db_chat.members if user.is_bot]


def get_chat_bots_id(chat: Chat | ChatData) -> list[int]:
    bots = get_chat_bots(chat)
    return [bot.id for bot in bots]


def get_chat_users_without_bots(chat: Chat | ChatData) -> list[UserData]:
    db_chat = add_chat(chat)
    return [user for user in db_chat.members if not user.is_bot]


def get_chat_users_without_bots_id(chat: Chat | ChatData) -> list[int]:
    users = get_chat_users_without_bots(chat)
    return [user.id for user in users]


def get_all_chats() -> list[ChatData]:
    return db.query(ChatData).all()


def get_all_chats_id() -> list[int]:
    return [chat.id for chat in get_all_chats()]
