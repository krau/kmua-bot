from telegram import ChatMember, ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from ..logger import logger


def extract_status_change(
    chat_member_update: ChatMemberUpdated,
) -> tuple([bool, bool]):
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was
    a member of the chat and whether the 'new_chat_member' is a member of the chat.
    Returns None, if the status didn't change.
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


async def chat_member_updated(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    # cause_member = update.chat_member.from_user
    updated_member = update.chat_member.new_chat_member.user

    if not was_member and is_member:
        # await update.effective_chat.send_message(
        #     f"{member_name} was added by {cause_name}. Welcome!",
        #     parse_mode="Markdown",
        # )
        pass
    elif was_member and not is_member:
        # await update.effective_chat.send_message(
        #     f"{member_name} is no longer with us. Thanks a lot, {cause_name} ...",
        #     parse_mode="Markdown",
        # )
        del context.chat_data["members_data"][updated_member.id]
        logger.debug(
            f"将 {updated_member.full_name} 从 {update.effective_chat.title} 数据中移除"
        )
