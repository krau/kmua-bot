from itertools import chain

from telegram import Chat, User

from ..dao.association import (
    get_association_in_chat_by_user,
    get_associations_of_user,
    get_associations_of_user_waifu_of,
)
from ..dao.chat import add_chat, get_chat_by_id
from ..dao.db import db
from ..dao.user import add_user, get_user_by_id
from ..models.models import ChatData, UserChatAssociation, UserData


def _get_user_waifu_in_chat_common(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    db_user = get_user_by_id(user.id)
    if db_user is None:
        add_user(user)
        return None
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return None
    association = get_association_in_chat_by_user(chat, user)
    if association is None:
        return None
    if association.waifu_id is None:
        return None
    return get_user_by_id(association.waifu_id)


def get_user_waifu_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    waifu = _get_user_waifu_in_chat_common(user, chat)
    if waifu is None:
        db_user = get_user_by_id(user.id)
        if db_user.married_waifu_id is not None:
            return get_user_by_id(db_user.married_waifu_id)
        return None
    return waifu


def get_user_waifu_in_chat_exclude_married(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    return _get_user_waifu_in_chat_common(user, chat)


def get_user_waifu_of_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> list[UserData] | None:
    """
    获取 user 被 chat 中的哪些人选为了 waifu

    :param user: User or UserData object
    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_user = get_user_by_id(user.id)
    if db_user is None:
        add_user(user)
        return None
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return None
    associations = (
        db.query(UserChatAssociation).filter_by(waifu_id=user.id, chat_id=chat.id).all()
    )
    if not associations:
        return None
    return [get_user_by_id(association.user_id) for association in associations]


def get_chat_married_users(chat: Chat | ChatData) -> list[UserData]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return [user for user in db_chat.members if user.is_married]


def get_chat_married_users_id(chat: Chat) -> list[int]:
    married_user = get_chat_married_users(chat)
    return [user.id for user in married_user]


def get_user_married_waifu(user: User) -> UserData | None:
    db_user = get_user_by_id(user.id)
    if db_user is None:
        add_user(user)
        return None
    if married_waifu_id := db_user.married_waifu_id:
        return get_user_by_id(married_waifu_id)
    return None


def put_user_waifu_in_chat(
    user: User | UserData, chat: Chat | ChatData, waifu: User | UserData
) -> bool:
    if get_user_waifu_in_chat_exclude_married(user, chat) is not None:
        return False
    if get_user_by_id(waifu.id) is None:
        add_user(waifu)
    if association := get_association_in_chat_by_user(chat, user):
        if association.waifu_id is None:
            association.waifu_id = waifu.id
            db.commit()
            return True
        else:
            return False
    else:
        db.add(
            UserChatAssociation(
                user_id=user.id,
                chat_id=chat.id,
                waifu_id=waifu.id,
            )
        )
        db.commit()
        return True


def refresh_user_waifu_in_chat(user: User | UserData, chat: Chat | ChatData):
    association = get_association_in_chat_by_user(chat, user)
    if association is None:
        return
    association.waifu_id = None
    db.commit()


def get_chat_users_has_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中有 waifu 的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_chat = add_chat(chat)
    return [
        user
        for user in db_chat.members
        if get_user_waifu_in_chat_exclude_married(user, chat) is not None
    ]


def get_chat_users_was_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中被选为 waifu 的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_chat = add_chat(chat)
    return [
        user
        for user in db_chat.members
        if get_user_waifu_of_in_chat(user, chat) is not None
    ]


def get_chat_user_participated_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中参与了抽老婆活动的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    user_has_waifu = get_chat_users_has_waifu(chat)
    user_was_waifu = get_chat_users_was_waifu(chat)
    return set(chain(user_has_waifu, user_was_waifu))


def refresh_all_waifu_in_chat(chat: Chat | ChatData):
    db_chat = add_chat(chat)
    for user in db_chat.members:
        refresh_user_waifu_in_chat(user, chat)


async def refresh_all_waifu_data():
    db.query(UserChatAssociation).update({UserChatAssociation.waifu_id: None})
    db.commit()


def refresh_user_all_waifu(user: User | UserData):
    db_user = add_user(user)
    associations = get_associations_of_user(db_user)
    for association in associations:
        association.waifu_id = None
    db.commit()


def get_user_waifus(user: User | UserData) -> list[UserData]:
    db_user = add_user(user)
    associations = get_associations_of_user(db_user)
    return [
        get_user_by_id(association.waifu_id)
        for association in associations
        if association.waifu_id is not None
    ]


def get_user_waifus_with_chat(user: User | UserData) -> list[tuple[UserData, ChatData]]:
    db_user = add_user(user)
    associations = get_associations_of_user(db_user)
    return [
        (
            get_user_by_id(association.waifu_id),
            get_chat_by_id(association.chat_id),
        )
        for association in associations
        if association.waifu_id is not None
    ]


def get_user_waifus_of(user: User | UserData) -> list[UserData]:
    db_user = add_user(user)
    associations = get_associations_of_user_waifu_of(db_user)
    return [get_user_by_id(association.user_id) for association in associations]


def get_user_waifus_of_with_chat(
    user: User | UserData,
) -> list[tuple[UserData, ChatData]]:
    db_user = add_user(user)
    associations = get_associations_of_user_waifu_of(db_user)
    return [
        (
            get_user_by_id(association.user_id),
            get_chat_by_id(association.chat_id),
        )
        for association in associations
    ]
