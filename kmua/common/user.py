from telegram import (
    Chat,
    Update,
    User,
)
from telegram.constants import ChatID, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import dao
from kmua.config import settings
from kmua.logger import logger
from kmua.models.models import ChatData, UserData

fake_users_id = [ChatID.FAKE_CHANNEL, ChatID.ANONYMOUS_ADMIN, ChatID.SERVICE_CHAT]


async def get_big_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    logger.debug(f"Get big avatar for {chat_id}")
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_big_blob:
            return db_user.avatar_big_blob
        avatar = await download_big_avatar(chat_id, context)
        if avatar:
            db_user.avatar_big_blob = avatar
            dao.commit()
        return avatar
    return await download_big_avatar(chat_id, context)


async def download_big_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    logger.debug(f"Downloading big avatar for {chat_id}")
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_big_file()).download_as_bytearray()
        avatar = bytes(avatar)
        logger.success(f"Success downloaded big avatar for {chat_id}")
        return avatar
    except Exception as err:
        logger.warning(f"Failed download: {err.__class__.__name__}: {err}")
        return None


async def get_small_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    logger.debug(f"Get small avatar for {chat_id}")
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_small_blob:
            return db_user.avatar_small_blob
        avatar = await download_small_avatar(chat_id, context)
        if avatar:
            db_user.avatar_small_blob = avatar
            dao.commit()
        return avatar
    return await download_small_avatar(chat_id, context)


async def download_small_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    logger.debug(f"Downloading small avatar for {chat_id}")
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_small_file()).download_as_bytearray()
        avatar = bytes(avatar)
        logger.success(f"Success downloaded small avatar for {chat_id}")
        return avatar
    except Exception as err:
        logger.warning(f"Failed download: {err.__class__.__name__}: {err}")
        return None


async def verify_user_is_chat_admin(
    user: User, chat: Chat, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否是群管理员

    :return: bool
    """
    logger.debug(
        f"Verify user {user.full_name}<{user.id}> is {chat.title}<{chat.id}> admin"
    )
    if chat.type == ChatType.PRIVATE:
        return False
    admins = await context.bot.get_chat_administrators(chat_id=chat.id)
    if user.id not in [admin.user.id for admin in admins]:
        return False
    return True


async def verify_user_is_chat_owner(
    user: User, chat: Chat, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否是群主,
    已在内部做 answer callback query 处理
    :return: bool
    """
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=user.id
        )
        if chat_member.status == ChatMemberStatus.OWNER:
            dao.update_user_is_bot_admin_in_chat(user, chat, True)
            return True
        if update.callback_query:
            await update.callback_query.answer(
                "你没有执行此操作的权限", show_alert=True, cache_time=15
            )
            dao.update_user_is_bot_admin_in_chat(user, chat, False)
    except Exception as err:
        logger.warning(f"{err.__class__.__name__}: {err}")
        if update.callback_query:
            await update.callback_query.answer(
                (
                    "无法获取成员信息, 如果开启了隐藏群成员, 请赋予 bot 管理员权限\n"
                    f"错误信息: {err.__class__.__name__}: {err}"
                ),
                show_alert=True,
                cache_time=15,
            )
    return False


def verify_user_can_manage_bot(user: User | UserData) -> bool:
    """
    校验用户是否有管理bot的权限(全局)
    """
    if user.id in settings.owners:
        return True
    if db_user := dao.get_user_by_id(user.id):
        return db_user.is_bot_global_admin
    return False


async def verify_user_can_manage_bot_in_chat(
    user: User, chat: Chat, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否有在该聊天中管理bot的权限
    可以管理bot的人包括: 群主 (和匿名管理员)、bot的全局管理员、在群中被群主授权的bot管理员
    已在内部做 answer callback query 处理
    :return: bool
    """
    logger.debug(
        f"Verify user {user.full_name}<{user.id}> "
        f"can manage bot in {chat.title}<{chat.id}>"
    )
    if chat.type == ChatType.PRIVATE:
        return False
    if (
        verify_user_can_manage_bot(user)
        or user.id == ChatID.ANONYMOUS_ADMIN
        or dao.get_user_is_bot_admin_in_chat(user, chat)
    ):
        return True
    if await verify_user_is_chat_owner(user, chat, update, context):
        return True
    return False


def get_user_info(user: User | UserData) -> str:
    db_user = dao.add_user(user)
    return str(db_user)


def mention_markdown_v2(user: User | UserData | Chat | ChatData) -> str:
    if isinstance(user, User) or isinstance(user, Chat):
        try:
            return user.mention_markdown_v2()
        except TypeError:
            return f"[{escape_markdown(user.title,2)}](tg://user?id={user.id})"
    else:
        db_user = dao.add_user(user)
        if not db_user.is_real_user and db_user.username is not None:
            return f"[{escape_markdown(db_user.full_name,2)}](https://t.me/{db_user.username})"
        return f"[{escape_markdown(db_user.full_name,2)}](tg://user?id={db_user.id})"
