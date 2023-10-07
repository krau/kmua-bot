from telegram import Chat

from ..dao.chat import get_chat_by_id, delete_chat
from ..dao import db
from ..dao.quote import delete_quote
from ..models.models import ChatData


def delete_chat_data_and_quotes(chat: Chat | ChatData):
    # 删除与该群组相关的所有数据
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        return
    for quote in db_chat.quotes:
        delete_quote(quote)
    delete_chat(db_chat)
    db.commit()


def update_chat_id(old_id: int, new_id: int):
    db_chat = get_chat_by_id(old_id)
    if db_chat is None:
        return
    if get_chat_by_id(new_id) is not None:
        return
    db_chat.id = new_id
    db.commit()


def update_chat_title(chat: Chat | ChatData, title: str):
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        return
    db_chat.title = title
    db.commit()
