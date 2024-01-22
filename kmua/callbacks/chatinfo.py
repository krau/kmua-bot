from pyrogram import Client, types, enums
from kmua.logger import logger


async def getid(client: Client, message: types.Message):
    logger.info(f"[{message.chat.title}] {message.text}")
    user = message.sender_chat or message.from_user
    if target_msg := message.reply_to_message:
        target = (
            target_msg.sender_chat
            or target_msg.forward_from
            or target_msg.forward_from_chat
            or target_msg.from_user
        )
        await message.reply_text(
            text=f"""
**Chat ID:** `{message.chat.id}`
**User ID:** `{user.id}`
**Target ID:** `{target.id}`
""",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    else:
        await message.reply_text(
            text=f"""
**Chat ID:** `{message.chat.id}`
**User ID:** `{user.id}`
""",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
