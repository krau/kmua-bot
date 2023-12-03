from telegram import Chat, User

from kmua.dao._db import commit, _db
from kmua.models import ChatData, UserChatAssociation, UserData


def get_association_in_chat(chat: Chat | ChatData) -> UserChatAssociation | None:
    return (
        _db.query(UserChatAssociation)
        .filter(UserChatAssociation.chat_id == chat.id)
        .all()
    )


def get_association_in_chat_by_user(
    chat: Chat | ChatData, user: User | UserData | Chat | ChatData
) -> UserChatAssociation | None:
    return (
        _db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.chat_id == chat.id,
            UserChatAssociation.user_id == user.id,
        )
        .first()
    )


def add_association_in_chat(
    chat: Chat | ChatData,
    user: User | UserData | Chat | ChatData,
    waifu: User | UserData | Chat | ChatData | None = None,
) -> UserChatAssociation:
    """
    add association if not exists(add user to chat)

    :param user: User or UserData object
    :param chat: Chat or ChatData object
    :return: UserChatAssociation object
    """
    if association := get_association_in_chat_by_user(chat, user):
        return association
    _db.add(
        UserChatAssociation(
            user_id=user.id,
            chat_id=chat.id,
            waifu_id=waifu.id if waifu else None,
        )
    )
    commit()
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
        _db.delete(association)
        commit()


def get_associations_of_user(user: User | UserData) -> list[UserChatAssociation]:
    return _db.query(UserChatAssociation).filter_by(user_id=user.id).all()


def get_associations_of_user_waifu_of_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> list[UserChatAssociation]:
    return (
        _db.query(UserChatAssociation)
        .filter_by(waifu_id=user.id, chat_id=chat.id)
        .all()
    )


def get_associations_of_user_waifu_of(
    user: User | UserData,
) -> list[UserChatAssociation]:
    return _db.query(UserChatAssociation).filter_by(waifu_id=user.id).all()


def update_associations_all_waifu_id_to_none():
    _db.query(UserChatAssociation).update({UserChatAssociation.waifu_id: None})
    _db.commit()


def get_all_associations_count() -> int:
    return _db.query(UserChatAssociation).count()
