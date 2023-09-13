from .db import db
from .model import UserData, ChatData, Quote, UserChatAssociation
from telegram import User, Chat
from itertools import chain


def commit():
    db.commit()


def get_user_by_id(user_id: int) -> UserData | None:
    return db.query(UserData).filter(UserData.id == user_id).first()


def get_chat_by_id(chat_id: int) -> ChatData | None:
    return db.query(ChatData).filter(ChatData.id == chat_id).first()


def get_quote_by_id(quote_id: int) -> Quote | None:
    return db.query(Quote).filter(Quote.quote_id == quote_id).first()


def get_chat_members(chat: Chat | ChatData) -> list[UserData]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return db_chat.members


def get_chat_members_id(chat: Chat | ChatData) -> list[int]:
    members = get_chat_members(chat)
    return [member.id for member in members]


def get_chat_association(chat: Chat | ChatData) -> ChatData | None:
    return (
        db.query(UserChatAssociation)
        .filter(UserChatAssociation.chat_id == chat.id)
        .all()
    )


def add_user(user: User | UserData) -> UserData:
    """
    add user if not exists

    :return: UserData object
    """
    if userdata := get_user_by_id(user.id):
        return userdata
    db.add(
        UserData(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
    )
    db.commit()
    return get_user_by_id(user.id)


def add_user_with_avatar(
    user: User | UserData, small_avatar: bytes, big_avatar: bytes, big_avatar_id: str
) -> bool:
    if userdata := get_user_by_id(user.id):
        userdata.avatar_small_blob = small_avatar
        userdata.avatar_big_blob = big_avatar
        userdata.avatar_big_id = big_avatar_id
        db.commit()
        return True
    db.add(
        UserData(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            avatar_small_blob=small_avatar,
            avatar_big_blob=big_avatar,
            avatar_big_id=big_avatar_id,
        )
    )
    db.commit()
    return True


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
        )
    )
    db.commit()
    return get_chat_by_id(chat.id)


def add_quote(
    chat: Chat, user: User, message_id: int, text: str = None, img: str = None
):
    db.add(
        Quote(
            chat_id=chat.id,
            user_id=user.id,
            message_id=message_id,
            text=text,
            img=img,
        )
    )
    db.commit()


def delete_quote(quote: Quote):
    pass


def get_chat_quote_probability(chat: Chat | ChatData) -> float:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return 0.001
    return db_chat.quote_probability


def set_chat_quote_probability(chat: Chat | ChatData, probability: float):
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        db_chat = get_chat_by_id(chat.id)
    db_chat.quote_probability = probability
    db.commit()


def add_user_to_chat(user: User | UserData, chat: Chat | ChatData):
    db_user = add_user(user)
    db_chat = add_chat(chat)
    if db_user not in db_chat.members:
        db_chat.members.append(db_user)
        db.commit()


def remove_user_from_chat(user: User | UserData, chat: Chat | ChatData):
    db_user = get_user_by_id(user.id)
    db_chat = get_chat_by_id(chat.id)
    if db_user is None or db_chat is None:
        return
    if db_user in db_chat.members:
        db_chat.members.remove(db_user)
        db.commit()


def get_user_association_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> UserChatAssociation | None:
    db_user = get_user_by_id(user.id)
    db_chat = get_chat_by_id(chat.id)
    if db_user is None or db_chat is None:
        return None
    return (
        db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.user_id == user.id,
            UserChatAssociation.chat_id == chat.id,
        )
        .first()
    )


def get_user_waifu_in_chat(
    user: User | UserData, chat: Chat | ChatData
) -> UserData | None:
    db_user = get_user_by_id(user.id)
    if db_user is None:
        add_user(user)
        return None
    if married_waifu_id := db_user.married_waifu_id:
        return add_user(married_waifu_id)
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return None
    association = get_user_association_in_chat(user, chat)
    if association is None:
        return None
    return get_user_by_id(association.waifu_id)


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
        db.query(UserChatAssociation)
        .filter(
            UserChatAssociation.waifu_id == user.id,
            UserChatAssociation.chat_id == chat.id,
        )
        .all()
    )
    if associations is None:
        return None
    return [get_user_by_id(association.user_id) for association in associations]


def get_married_users_in_chat(chat: Chat | ChatData) -> list[UserData]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return [
        user
        for user in db_chat.members
        if user.is_married and user.married_waifu_id is not None
    ]


def get_married_users_id_in_chat(chat: Chat) -> list[int]:
    married_user = get_married_users_in_chat(chat)
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
    if get_user_waifu_in_chat(user, chat) is not None:
        return False
    if get_user_by_id(waifu.id) is None:
        add_user(waifu)
    if association := get_user_association_in_chat(user, chat):
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
    association = get_user_association_in_chat(user, chat)
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
        if get_user_waifu_in_chat(user, chat) is not None
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


def get_all_chats() -> list[ChatData]:
    return db.query(ChatData).all()


def get_all_chats_id() -> list[int]:
    return [chat.id for chat in get_all_chats()]


def refresh_all_waifu_in_chat(chat: Chat | ChatData):
    db_chat = add_chat(chat)
    for user in db_chat.members:
        refresh_user_waifu_in_chat(user, chat)


def refresh_all_waifu_data():
    db.query(UserChatAssociation).update({UserChatAssociation.waifu_id: None})
    db.commit()