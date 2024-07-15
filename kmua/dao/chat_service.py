from telegram import Chat

import kmua.dao.chat as chat_dao
import kmua.dao.quote as quote_dao
from kmua.models.models import ChatData

from ._db import commit


def delete_chat_data_and_quotes(chat_id: int):
    db_chat = chat_dao.get_chat_by_id(chat_id)
    if db_chat is None:
        return
    quote_dao.delete_chat_quotes(db_chat)
    chat_dao.delete_chat(db_chat)
    commit()


def update_chat_id(old_id: int, new_id: int):
    db_chat = chat_dao.get_chat_by_id(old_id)
    if db_chat is None:
        return
    if chat_dao.get_chat_by_id(new_id) is not None:
        return
    db_chat.id = new_id
    commit()


def update_chat_title(chat: Chat | ChatData, title: str):
    db_chat = chat_dao.get_chat_by_id(chat.id)
    if db_chat is None:
        return
    db_chat.title = title
    commit()