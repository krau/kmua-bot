import datetime

from sqlalchemy import text
from telegram import Chat, User

from kmua.dao._db import _db, commit
from kmua.models.models import ChatData, Quote, UserData


def get_user_by_id(user_id: int) -> UserData | None:
    return _db.query(UserData).filter(UserData.id == user_id).first()


def add_user(user: User | UserData | Chat | ChatData) -> UserData:
    """
    添加用户，如果用户已存在则返回已存在的用户
    如果传递的是 Chat 或 ChatData 对象，full_name 为 chat.title

    :return: UserData object
    """
    if userdata := get_user_by_id(user.id):
        return userdata
    userdata = None
    if isinstance(user, (Chat, ChatData)):
        userdata = UserData(
            id=user.id,
            username=user.username,
            full_name=user.title,
            waifu_mention=True,
            is_real_user=False,
        )
    elif isinstance(user, User) and user.is_bot:
        userdata = UserData(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            is_real_user=False,
            is_bot=True,
            waifu_mention=True,
        )
    elif isinstance(user, User):
        userdata = UserData(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
    _db.add(userdata)
    commit()
    return get_user_by_id(user.id)


def get_user_is_bot_global_admin(user: User | UserData) -> bool:
    return add_user(user).is_bot_global_admin


def update_user_is_bot_global_admin(user: User | UserData, is_admin: bool):
    _db_user = add_user(user)
    _db_user.is_bot_global_admin = is_admin
    commit()


def get_user_quotes(user: User | UserData) -> list[Quote]:
    _db_user = add_user(user)
    return _db_user.quotes


def get_user_quotes_count(user: User | UserData) -> int:
    return _db.query(Quote).filter(Quote.user_id == user.id).count()


def get_user_quotes_page(
    user: User | UserData, page: int, page_size: int
) -> list[Quote]:
    offset = (page - 1) * page_size
    return (
        _db.query(Quote)
        .filter(Quote.user_id == user.id)
        .offset(offset)
        .limit(page_size)
        .all()
    )


def get_qer_quotes_count(user: User | UserData) -> int:
    return _db.query(Quote).filter(Quote.qer_id == user.id).count()


def get_qer_quotes_page(
    user: User | UserData, page: int, page_size: int
) -> list[Quote]:
    offset = (page - 1) * page_size
    return (
        _db.query(Quote)
        .filter(Quote.qer_id == user.id)
        .offset(offset)
        .limit(page_size)
        .all()
    )


def get_all_users_count() -> int:
    return _db.query(UserData).count()


def get_inactived_users_count(days: int) -> int:
    return (
        _db.query(UserData)
        .filter(
            UserData.updated_at
            < datetime.datetime.now() - datetime.timedelta(days=days)
        )
        .count()
    )


def clear_inactived_users_avatar(days: int) -> int:
    count = (
        _db.query(UserData)
        .filter(
            UserData.updated_at
            < datetime.datetime.now() - datetime.timedelta(days=days)
        )
        .update(
            {
                UserData.avatar_big_id: None,
                UserData.avatar_small_blob: None,
                UserData.avatar_big_blob: None,
            }
        )
    )
    commit()
    _db.flush()
    _db.execute(text("VACUUM"))
    commit()
    _db.flush()
    return count


def get_bot_global_admins() -> list[UserData]:
    return _db.query(UserData).filter(UserData.is_bot_global_admin).all()