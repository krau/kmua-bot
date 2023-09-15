import asyncio

from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from ..dao.association import delete_association_in_chat
from ..logger import logger
from ..service.chat import delete_chat_data


def extract_status_change(chat_member_update: ChatMemberUpdated):
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
    """Tracks the chats the bot is in."""
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
            logger.debug(f"{cause_name} started the bot")

        elif was_member and not is_member:
            logger.debug(f"{cause_name} blocked the bot")

    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logger.debug(f"{cause_name} 将bot添加到群组 {chat.title}")

        elif was_member and not is_member:
            logger.debug(f"{cause_name} 将bot移出群组 {chat.title}")
            delete_chat_data(chat)

    elif not was_member and is_member:
        logger.debug(f"{cause_name} 将bot添加到频道 {chat.title}")
        try:
            await asyncio.sleep(3)
            await context.bot.leave_chat(chat.id)
        except Exception as err:
            logger.error(f"退出频道时出错 {chat.title}: {err}")

    elif was_member and not is_member:
        logger.debug(f"{cause_name} 将bot移出频道 {chat.title}")


async def on_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    left_user = update.effective_message.left_chat_member
    logger.debug(f"{left_user.full_name} 退出了群聊 {update.effective_chat.title}")
    delete_association_in_chat(update.effective_chat, left_user.id)


async def on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    joined_user = update.effective_message.new_chat_members[0]
    logger.debug(f"{joined_user} 加入了群聊 {update.effective_chat.title} ")


async def set_greet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
