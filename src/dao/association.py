from telegram import Chat, User

from ..models.models import ChatData, UserChatAssociation, UserData
from .db import db, commit


def get_association_in_chat(chat: Chat | ChatData) -> UserChatAssociation | None:
    return (
        db.query(UserChatAssociation)
        .filter(UserChatAssociation.chat_id == chat.id)
        .all()
    )


def get_association_in_chat_by_user(
    chat: Chat | ChatData, user: User | UserData | Chat | ChatData
) -> UserChatAssociation | None:
    return (
        db.query(UserChatAssociation)
        .filter(UserChatAssociation.chat_id == chat.id)
        .filter(UserChatAssociation.user_id == user.id)
        .first()
    )


def add_association_in_chat(
    chat: Chat | ChatData, user: User | UserData | Chat | ChatData
) -> UserChatAssociation:
    """
    add association if not exists(add user to chat)

    :param user: User or UserData object
    :param chat: Chat or ChatData object
    :return: UserChatAssociation object
    """
    if association := get_association_in_chat_by_user(chat, user):
        return association
    db.add(
        UserChatAssociation(
            user_id=user.id,
            chat_id=chat.id,
        )
    )
    commit
    return get_association_in_chat_by_user(chat, user)


def delete_association_in_chat(
    chat: Chat | ChatData, user: User | UserData | Chat | ChatData
):
    """
    delete association if exists(delete user from chat)

    :param user: User or UserData object
    :param chat: Chat or ChatData object
    """
    if association := get_association_in_chat_by_user(chat, user):
        db.delete(association)
        commit()


def get_associations_of_user(user: User | UserData) -> list[UserChatAssociation]:
    return db.query(UserChatAssociation).filter_by(user_id=user.id).all()


def get_associations_of_user_waifu_of(
    user: User | UserData,
) -> list[UserChatAssociation]:
    return db.query(UserChatAssociation).filter_by(waifu_id=user.id).all()
