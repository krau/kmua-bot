from pyrogram import types
from kmua.config import settings


def verify_user_can_manage_bot(user: types.User | types.Chat) -> bool:
    if user.id in settings.owners:
        return True
    return False
