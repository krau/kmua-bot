from telegram import Chat, User

from kmua.dao._db import commit, _db
from kmua.models import ChatData, Quote, UserData


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
    if isinstance(user, Chat) or isinstance(user, ChatData):
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
    return len(get_user_quotes(user))


def get_user_quotes_page(
    user: User | UserData, page: int, page_size: int
) -> list[Quote]:
    return get_user_quotes(user)[(page - 1) * page_size : page * page_size]


def get_all_users_count() -> int:
    return _db.query(UserData).count()
