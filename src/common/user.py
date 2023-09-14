from telegram import (
    Chat,
    Update,
    User,
)
from telegram.constants import ChatID, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from ..config import settings
from ..database import dao
from ..database.model import UserData
from ..logger import logger


async def get_big_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_big_blob:
            return db_user.avatar_big_blob
        else:
            avatar = await download_big_avatar(chat_id, context)
            if avatar:
                db_user.avatar_big_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_big_avatar(chat_id, context)


async def download_big_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_big_file()).download_as_bytearray()
        avatar = bytes(avatar)
        return avatar
    except Exception as err:
        logger.error(f"{err.__class__.__name__}: {err} happend when getting big avatar")
        return None


async def get_small_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_small_blob:
            return db_user.avatar_small_blob
        else:
            avatar = await download_small_avatar(chat_id, context)
            if avatar:
                db_user.avatar_small_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_small_avatar(chat_id, context)


async def download_small_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_small_file()).download_as_bytearray()
        avatar = bytes(avatar)
        return avatar
    except Exception as err:
        logger.error(
            f"{err.__class__.__name__}: {err} happend when getting small avatar"
        )
        return None


async def verify_user_is_chat_admin(
    user: User, chat: Chat, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否是群管理员

    :return: bool
    """
    if chat.type == ChatType.PRIVATE:
        return False
    admins = await context.bot.get_chat_administrators(chat_id=chat.id)
    if user.id not in [admin.user.id for admin in admins]:
        return False
    return True


async def verify_user_can_manage_bot(
    user: User, chat: Chat, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否有在该聊天中管理bot的权限
    可以管理bot的人包括：群主（和匿名管理员）、bot的全局管理员、在群中被群主授权的bot管理员
    已在内部做 answer callback query 处理
    :return: bool
    """
    if chat.type == ChatType.PRIVATE:
        return False
    if (
        user.id in settings.owners
        or user.id == ChatID.ANONYMOUS_ADMIN
        or dao.get_user_is_bot_global_admin(user)
        or dao.get_user_is_bot_admin_in_chat(user, chat)
    ):
        return True
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=user.id
        )
        if chat_member.status == ChatMemberStatus.OWNER:
            return True
        if update.callback_query:
            await update.callback_query.answer(
                "你没有执行此操作的权限", show_alert=False, cache_time=10
            )
    except Exception as err:
        logger.warning(f"{err.__class__.__name__}: {err}")
        if update.callback_query:
            await update.callback_query.answer(
                (
                    "无法获取成员信息, 如果开启了隐藏群成员, 请赋予 bot 管理员权限\n"
                    f"错误信息: {err.__class__.__name__}: {err}"
                ),
                show_alert=True,
                cache_time=5,
            )
        return False
    return False


def get_user_info(user: User | UserData) -> str:
    db_user = dao.add_user(user)
    info = f"""
id: {db_user.id}
username: {db_user.username}
full_name: {db_user.full_name}
头像缓存id(大尺寸): {True if db_user.avatar_big_id else None}
头像(大尺寸): {True if db_user.avatar_big_blob else None}
头像(小尺寸): {True if db_user.avatar_small_blob else None}
已结婚: {db_user.is_married}
已结婚的老婆id: {db_user.married_waifu_id}
是否为bot全局管理: {db_user.is_bot_global_admin}
created_at: {db_user.created_at.strftime("%Y-%m-%d %H:%M:%S")}
updated_at: {db_user.updated_at.strftime("%Y-%m-%d %H:%M:%S")}
"""
    return info
