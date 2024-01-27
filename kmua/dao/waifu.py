from itertools import chain

from telegram import Chat, User

import kmua.dao.association as association_dao
import kmua.dao.chat as chat_dao
import kmua.dao.user as user_dao
from kmua.models.models import ChatData, UserChatAssociation, UserData

from ._db import _db, commit


def _get_user_waifu_in_chat_common(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    db_user = user_dao.get_user_by_id(user.id)
    if db_user is None:
        user_dao.add_user(user)
        return None
    db_chat = chat_dao.get_chat_by_id(chat.id)
    if db_chat is None:
        chat_dao.add_chat(chat)
        return None
    association = association_dao.get_association_in_chat_by_user(chat, user)
    if association is None:
        return None
    if association.waifu_id is None:
        return None
    return user_dao.get_user_by_id(association.waifu_id)


def get_user_waifu_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    waifu = _get_user_waifu_in_chat_common(user, chat)
    if waifu is None:
        db_user = user_dao.get_user_by_id(user.id)
        if db_user.married_waifu_id is not None:
            return user_dao.get_user_by_id(db_user.married_waifu_id)
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
    db_user = user_dao.get_user_by_id(user.id)
    if db_user is None:
        user_dao.add_user(user)
        return None
    db_chat = chat_dao.get_chat_by_id(chat.id)
    if db_chat is None:
        chat_dao.add_chat(chat)
        return None
    associations = association_dao.get_associations_of_user_waifu_of_in_chat(
        db_user, db_chat
    )
    if not associations:
        return None
    return [
        user_dao.get_user_by_id(association.user_id) for association in associations
    ]


def get_chat_married_users(chat: Chat | ChatData) -> list[UserData]:
    db_chat = chat_dao.get_chat_by_id(chat.id)
    if db_chat is None:
        chat_dao.add_chat(chat)
        return []
    return [user for user in db_chat.members if user.is_married]


def get_chat_married_users_id(chat: Chat) -> list[int]:
    married_user = get_chat_married_users(chat)
    return [user.id for user in married_user]


def get_user_married_waifu(user: User) -> UserData | None:
    db_user = user_dao.get_user_by_id(user.id)
    if db_user is None:
        user_dao.add_user(user)
        return None
    if married_waifu_id := db_user.married_waifu_id:
        return user_dao.get_user_by_id(married_waifu_id)
    return None


def put_user_waifu_in_chat(
    user: User | UserData, chat: Chat | ChatData, waifu: User | UserData
) -> bool:
    if get_user_waifu_in_chat_exclude_married(user, chat) is not None:
        return False
    if user_dao.get_user_by_id(waifu.id) is None:
        user_dao.add_user(waifu)
    if association := association_dao.get_association_in_chat_by_user(chat, user):
        if association.waifu_id is None:
            association.waifu_id = waifu.id
            commit()
            return True
        return False
    association_dao.add_association_in_chat(chat, user, waifu)
    commit()
    return True


def refresh_user_waifu_in_chat(user: User | UserData, chat: Chat | ChatData):
    association = association_dao.get_association_in_chat_by_user(chat, user)
    if association is None:
        return
    association.waifu_id = None
    commit()


def get_chat_users_has_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中有 waifu 的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_chat = chat_dao.add_chat(chat)
    associations = (
        _db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.chat_id == db_chat.id,
            UserChatAssociation.waifu_id is not None,
        )
        .all()
    )
    return [
        user_dao.get_user_by_id(association.user_id) for association in associations
    ]


def get_chat_users_was_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中被选为 waifu 的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_chat = chat_dao.add_chat(chat)
    associations = (
        _db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.chat_id == db_chat.id,
            UserChatAssociation.waifu_id is not None,
        )
        .all()
    )
    return [
        user_dao.get_user_by_id(association.waifu_id) for association in associations
    ]


def get_chat_user_participated_waifu(chat: Chat | ChatData) -> list[UserData]:
    """
    获取 chat 中参与了抽老婆活动的人

    :param chat: Chat or ChatData object
    :return: list of UserData object
    """
    db_chat = chat_dao.add_chat(chat)
    associations = (
        _db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.chat_id == db_chat.id,
            UserChatAssociation.waifu_id.isnot(None),
        )
        .all()
    )
    users_id_has_waifu = [association.user_id for association in associations]
    users_id_was_waifu = [
        association.waifu_id
        for association in associations
        if association.waifu_id is not None
    ]
    users_id_participated = list(set(chain(users_id_has_waifu, users_id_was_waifu)))
    return [user_dao.get_user_by_id(user_id) for user_id in users_id_participated]


async def refresh_all_waifu_data():
    association_dao.update_associations_all_waifu_id_to_none()
    commit()


def refresh_user_all_waifu(user: User | UserData):
    db_user = user_dao.add_user(user)
    associations = association_dao.get_associations_of_user(db_user)
    for association in associations:
        association.waifu_id = None
    commit()


def get_user_waifus(user: User | UserData) -> list[UserData]:
    db_user = user_dao.add_user(user)
    associations = association_dao.get_associations_of_user(db_user)
    return [
        user_dao.get_user_by_id(association.waifu_id)
        for association in associations
        if association.waifu_id is not None
    ]


def get_user_waifus_with_chat(user: User | UserData) -> list[tuple[UserData, ChatData]]:
    db_user = user_dao.add_user(user)
    associations = association_dao.get_associations_of_user(db_user)
    return [
        (
            user_dao.get_user_by_id(association.waifu_id),
            chat_dao.get_chat_by_id(association.chat_id),
        )
        for association in associations
        if association.waifu_id is not None
    ]


def get_user_waifus_of(user: User | UserData) -> list[UserData]:
    db_user = user_dao.add_user(user)
    associations = association_dao.get_associations_of_user_waifu_of(db_user)
    return [
        user_dao.get_user_by_id(association.user_id) for association in associations
    ]


def get_user_waifus_of_with_chat(
    user: User | UserData,
) -> list[tuple[UserData, ChatData]]:
    db_user = user_dao.add_user(user)
    associations = association_dao.get_associations_of_user_waifu_of(db_user)
    return [
        (
            user_dao.get_user_by_id(association.user_id),
            chat_dao.get_chat_by_id(association.chat_id),
        )
        for association in associations
    ]
