from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import ChatMemberUpdated, Message

from kmua import common, database
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger


@Client.on_chat_member_updated(filters.group, group=0)
async def chat_member_updated(client: Client, chat_member_updated: ChatMemberUpdated):
    """
    seems only group admin can receive this event
    """
    chat = chat_member_updated.chat
    old_obj = chat_member_updated.old_chat_member
    new_obj = chat_member_updated.new_chat_member
    """
    1. old_obj is None, new_obj.user is not None:
         This means a new user has joined the chat.
    2. old_obj is not None, new_obj is None:
        This means a user has left the chat.
    3. both old_obj and new_obj are not None, but new_obj.status == BANNED:
        This means a user has been banned from the chat.
    ---
    other cases we don't care about:
    4. new_obj is None, old_obj.status == BANNED:
        This means a user has been unbanned from the chat, but the user is not in the chat.
    5. old_obj is not None, new_obj is not None, new_obj.status != BANNED:
        This means a user has changed their status in the chat (e.g., from member to admin).
    """
    if not any((old_obj, new_obj)):
        return
    user = new_obj.user if new_obj else old_obj.user
    if user is None:
        return
    if user.is_deleted:
        logger.warning(f"User is deleted: {user.id}")
        return
    if user.full_name is None:
        logger.warning(f"user.full_name is None: {user}")
        return
    db_user = await database.upsert_user(user)
    db_chat = await database.upsert_chat(chat)
    if not db_user or not db_chat:
        return
    # if old_obj is None and new_obj is not None:
    #     # Joined the chat
    #     logger.info(f"[{chat.id}]({user.id}): {user.full_name} joined the chat")
    #     await database.add_association_in_chat(db_chat, db_user)
    if (old_obj is not None and old_obj.user and new_obj is None) or (
        old_obj is not None
        and new_obj is not None
        and new_obj.status == ChatMemberStatus.BANNED
    ):
        logger.info(f"[{chat.id}]({user.id}): {user.full_name} left the chat")
        await database.remove_association(db_user.id, db_chat.id)


@Client.on_message(filters.group & filters.left_chat_member, group=0)
async def on_left_chat_member(client: Client, message: Message):
    """
    Handle the event when a user leaves a group chat.
    This is a fallback for cases where the chat_member_updated event does not trigger.
    """
    chat = message.chat
    user = message.left_chat_member
    if not user or not chat:
        return
    db_user = await database.upsert_user(user)
    db_chat = await database.upsert_chat(chat)
    if not db_user or not db_chat:
        return
    logger.info(f"[{chat.id}]({user.id}): {user.full_name} left the chat")
    await database.remove_association(db_user.id, db_chat.id)


@Client.on_message(filters.group & filters.command("syncmembers"), group=0)
async def sync_chat_members(client: Client, message: Message):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not user or not chat or not chat.id:
        return
    db_chat = await database.upsert_chat(chat)
    if not db_chat:
        logger.error(f"Failed to upsert chat {chat.id}")
        return
    lang = db_chat.chat_config.lang
    if not await common.can_user_manage_bot_in_chat(user, chat):
        await message.reply_text(i18n.t("bot.msg.no_permission_group", locale=lang))
        return
    if await common.memttlcache.get(f"sync_members:{chat.id}"):
        await message.reply_text(i18n.t("bot.msg.sync_members_cd", locale=lang))
        return
    await common.memttlcache.set(
        f"sync_members:{chat.id}", True, app_config.cachettl_sync_members
    )
    await message.reply_text(i18n.t("bot.msg.sync_members_start", locale=lang))
    # 在数据库中删除已经不在群组中的用户
    try:
        current_members = client.get_chat_members(chat.id)
        current_member_ids = {member.user.id async for member in current_members}
    except Exception as e:
        logger.error(f"Failed to get current members for chat {chat.id}: {e}")
        await message.reply_text(i18n.t("bot.msg.sync_members_error", locale=lang))
        return
    db_associations = await database.get_chat_associations(chat.id)
    db_member_ids = {assoc.user_id for assoc in db_associations}
    to_remove = db_member_ids - current_member_ids
    oks = 0
    for user_id in to_remove:
        ok = await database.remove_association(user_id, chat.id)
        if not ok:
            logger.warning(
                f"Failed to remove association for user {user_id} in chat {chat.id}"
            )
            continue
        oks += 1
        await database.unset_chat_waifus_by_waifu(db_chat, user_id)
    await message.reply_text(
        i18n.t("bot.msg.sync_members_done", locale=lang).format(count=oks)
    )
    logger.info(
        f"Synced members for chat {chat.id} ({chat.title}), removed {oks} members"
    )
