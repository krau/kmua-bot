from telegram import Chat, User

from ..dao.association import add_association_in_chat, get_association_in_chat_by_user
from ..dao.chat import get_chat_by_id
from ..dao import db
from ..dao.user import get_user_by_id
from ..models.models import ChatData, UserData


def get_user_is_bot_admin_in_chat(user: User | UserData, chat: Chat | ChatData) -> bool:
    association = get_association_in_chat_by_user(chat, user)
    if association is None:
        return False
    return association.is_bot_admin


def update_user_is_bot_admin_in_chat(
    user: User | UserData, chat: Chat | ChatData, is_admin: bool
):
    association = get_association_in_chat_by_user(chat, user)
    if association is None:
        add_association_in_chat(chat, user)
        association = get_association_in_chat_by_user(chat, user)
        association.is_bot_admin = is_admin
        db.commit()
        return
    association.is_bot_admin = is_admin
    db.commit()


def check_user_in_chat(user: User | UserData, chat: Chat | ChatData) -> bool:
    db_user = get_user_by_id(user.id)
    db_chat = get_chat_by_id(chat.id)
    if db_user is None or db_chat is None:
        return False
    return db_user in db_chat.members
