import asyncio

from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger


def extract_status_change(chat_member_update: ChatMemberUpdated) -> tuple[bool, bool]:
    """
    Extracts the status change from a ChatMemberUpdated object.

    :param chat_member_update: The ChatMemberUpdated object.
    :return: A tuple of (old_status, new_status) or None if no change happened.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get(
        "is_member", (None, None)
    )

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member


async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Track chats the bot is added to or removed from.

    :param update: Update
    :param context: Context
    """
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    # Let's check who is responsible for the change
    cause_name = update.effective_user.full_name

    # Handle chat types differently:
    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        if not was_member and is_member:
            logger.info(f"{cause_name} started the bot")

        elif was_member and not is_member:
            logger.info(f"{cause_name} blocked the bot")

    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logger.info(f"{cause_name} 将bot添加到群组 {chat.title}")

        elif was_member and not is_member:
            logger.info(f"{cause_name} 将bot移出群组 {chat.title}")

    elif not was_member and is_member:
        logger.info(f"{cause_name} 将bot添加到频道 {chat.title}")
        try:
            await asyncio.sleep(3)
            await context.bot.leave_chat(chat.id)
        except Exception as err:
            logger.error(f"退出频道时出错 {chat.title}: {err}")

    elif was_member and not is_member:
        logger.info(f"{cause_name} 将bot移出频道 {chat.title}")


async def on_member_left(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    Callback when a user leaves a chat.

    :param update: Update
    :param _: Context
    """
    left_user = update.effective_message.left_chat_member
    logger.debug(f"{left_user.full_name} 退出了群聊 {update.effective_chat.title}")
    dao.delete_association_in_chat(update.effective_chat, left_user)


async def on_member_join(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    Callback when a user joins a chat.

    :param update: Update
    :param _: Context
    """
    chat = update.effective_chat
    joined_user = update.effective_message.new_chat_members[0]
    logger.debug(f"{joined_user} 加入了群聊 {chat.title} ")
    if joined_user.is_bot:
        return
    db_chat = dao.add_chat(chat)
    greet = db_chat.greet
    if greet:
        greet = greet.format(
            user=joined_user.full_name,
            chat=chat.title,
        )
        message = update.effective_message
        await message.reply_text(text=greet)


async def set_greet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置入群欢迎

    :param update: Update
    :param context: Context
    """
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <set_greet>")
    message = update.effective_message
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await message.reply_text("你没有权限哦")
        return
    greet = " ".join(context.args)
    dao.update_chat_greet(chat, greet)
    if greet:
        await message.reply_text("设置成功")
    else:
        await message.reply_text("已清除入群欢迎")
