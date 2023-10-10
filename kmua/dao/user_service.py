from telegram import Chat, User
import kmua.dao.association as association_dao
import kmua.dao.chat as chat_dao
import kmua.dao.user as user_dao
from ._db import commit
from kmua.models import ChatData, UserData


def get_user_is_bot_admin_in_chat(user: User | UserData, chat: Chat | ChatData) -> bool:
    association = association_dao.get_association_in_chat_by_user(chat, user)
    if association is None:
        return False
    return association.is_bot_admin


def update_user_is_bot_admin_in_chat(
    user: User | UserData, chat: Chat | ChatData, is_admin: bool
):
    association = association_dao.get_association_in_chat_by_user(chat, user)
    if association is None:
        association_dao.add_association_in_chat(chat, user)
        association = association_dao.get_association_in_chat_by_user(chat, user)
        association.is_bot_admin = is_admin
        commit()
        return
    association.is_bot_admin = is_admin
    commit()


def check_user_in_chat(user: User | UserData, chat: Chat | ChatData) -> bool:
    db_user = user_dao.get_user_by_id(user.id)
    db_chat = chat_dao.get_chat_by_id(chat.id)
    if db_user is None or db_chat is None:
        return False
    return db_user in db_chat.members
