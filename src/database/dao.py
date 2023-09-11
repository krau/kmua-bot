from .db import db
from .model import UserData, ChatData, Quote
from telegram import User, Chat


def get_user_by_id(user_id: int) -> UserData:
    return db.query(UserData).filter(UserData.user_id == user_id).first()


def get_chat_by_id(chat_id: int) -> ChatData:
    return db.query(ChatData).filter(ChatData.chat_id == chat_id).first()


def get_quote_by_id(quote_id: int) -> Quote:
    return db.query(Quote).filter(Quote.quote_id == quote_id).first()


def get_chat_members_id(chat: Chat) -> list[int]:
    db_chat = get_chat_by_id(chat.id)
    if db_chat is None:
        add_chat(chat)
        return []
    return [user.user_id for user in db_chat.members]


def add_user(user: User) -> bool:
    if get_user_by_id(user.id) is not None:
        return False
    db.add(
        UserData(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
    )
    db.commit()
    return True


def add_user_with_avatar(
    user: User, small_avatar: bytes, big_avatar: bytes, big_avatar_id: str
) -> bool:
    if get_user_by_id(user.id) is not None:
        return False
    db.add(
        UserData(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            avatar_small_blob=small_avatar,
            avatar_big_blob=big_avatar,
            avatar_big_id=big_avatar_id,
        )
    )
    db.commit()
    return True


def add_chat(chat: Chat) -> bool:
    if get_chat_by_id(chat.id) is not None:
        return False
    db.add(ChatData(chat_id=chat.id, quote_probability=0.001))
    db.commit()
    return True


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
