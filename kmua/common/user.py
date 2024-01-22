from pyrogram import Client
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import CallbackQuery, Chat, User

from kmua import dao
from kmua.config import settings
from kmua.logger import logger
from kmua.models.models import UserData


async def verify_user_is_chat_admin(
    user: User, chat: Chat, callback_query: CallbackQuery = None
) -> bool:
    logger.debug(
        f"Verify user {user.full_name}<{user.id}> is {chat.title}<{chat.id}> admin"
    )
    if chat.type == ChatType.PRIVATE:
        return False
    try:
        member = await chat.get_member(user.id)
        if member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return True
        if callback_query:
            await callback_query.answer("你没有执行此操作的权限", show_alert=True, cache_time=15)
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        if callback_query:
            await callback_query.answer(
                "无法获取成员信息, 如果开启了隐藏群成员, 请赋予 bot 管理员权限\n"
                f"错误信息: {e.__class__.__name__}: {e}",
                show_alert=True,
                cache_time=15,
            )
    return False


async def verify_user_is_chat_owner(
    user: User, chat: Chat, callback_query: CallbackQuery = None
) -> bool:
    logger.debug(
        f"Verify user {user.full_name}<{user.id}> is {chat.title}<{chat.id}> owner"
    )
    if chat.type == ChatType.PRIVATE:
        return False
    try:
        member = await chat.get_member(user.id)
        if member.status == ChatMemberStatus.OWNER:
            return True
        if callback_query:
            await callback_query.answer("你没有执行此操作的权限", show_alert=True, cache_time=15)
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        if callback_query:
            await callback_query.answer(
                "无法获取成员信息, 如果开启了隐藏群成员, 请赋予 bot 管理员权限\n"
                f"错误信息: {e.__class__.__name__}: {e}",
                show_alert=True,
                cache_time=15,
            )
    return False


def verify_user_can_manage_bot(user: User | UserData) -> bool:
    """
    检验用户是否有管理bot的权限(全局)
    """
    if user.id in settings.owners:
        return True
    if db_user := dao.get_user_by_id(user.id):
        return db_user.is_bot_global_admin
    return False


async def verify_user_can_manage_bot_in_chat(
    user: User, chat: Chat, callback_query: CallbackQuery = None
) -> bool:
    """
    验证用户是否有在该聊天中管理bot的权限
    可以管理bot的人包括：群主（和匿名管理员）、bot的全局管理员、在群中被群主授权的bot管理员
    已在内部做 answer callback query 处理
    :return: bool
    """
    logger.debug(
        f"Verify user {user.full_name}<{user.id}> can manage bot in {chat.title}<{chat.id}>"  # noqa: E501
    )
    if chat.type == ChatType.PRIVATE:
        return False
    if (
        verify_user_can_manage_bot(user)
        or user.id == 1087968824
        or dao.get_user_is_bot_admin_in_chat(user, chat)
    ):
        return True
    if await verify_user_is_chat_owner(user, chat, callback_query):
        return True
    return False


def get_user_info(user: User | UserData) -> str:
    logger.debug(f"Get user info for {user.full_name}<{user.id}>")
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


async def get_big_avatar(chat_id: int, client: Client) -> bytes | None:
    logger.debug(f"Get big avatar for {chat_id}")
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_big_blob:
            return db_user.avatar_big_blob
        else:
            avatar = await download_big_avatar(chat_id, client)
            if avatar:
                db_user.avatar_big_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_big_avatar(chat_id, client)


async def get_small_avatar(chat_id: int, client: Client) -> bytes | None:
    logger.debug(f"Get small avatar for {chat_id}")
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_small_blob:
            return db_user.avatar_small_blob
        else:
            avatar = await download_small_avatar(chat_id, client)
            if avatar:
                db_user.avatar_small_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_big_avatar(chat_id, client)


async def download_big_avatar(chat_id: int, client: Client) -> bytes | None:
    logger.debug(f"Download big avatar for {chat_id}")
    try:
        chat = await client.get_chat(chat_id=chat_id)
        if chat.photo:
            file = await client.download_media(
                message=chat.photo.big_file_id, in_memory=True
            )
            with open(file, "rb") as f:
                return f.read()
        else:
            return None
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        return None


async def download_small_avatar(chat_id: int, client: Client) -> bytes | None:
    logger.debug(f"Download small avatar for {chat_id}")
    try:
        chat = await client.get_chat(chat_id=chat_id)
        if chat.photo:
            file = await client.download_media(
                message=chat.photo.small_file_id, in_memory=True
            )
            with open(file, "rb") as f:
                return f.read()
        else:
            return None
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        return None
