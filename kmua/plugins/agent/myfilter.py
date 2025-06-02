import pyrogram
from pyrogram import filters

from kmua.config import app_config


async def base_filter_func(_, __, message: pyrogram.types.Message) -> bool:
    if not app_config.agent:
        return False
    if not message or not message.text:
        return False
    if len(message.text) <= 1:
        return False
    if (
        message.entities is not None
        and message.entities[0].type == pyrogram.enums.MessageEntityType.BOT_COMMAND
    ):
        return False
    if message.text.startswith("/") or message.text.startswith("\\"):
        return False
    return True


async def reply_me_filter_func(
    _, client: pyrogram.Client, message: pyrogram.types.Message
) -> bool:
    if not message.reply_to_message:
        return False
    if not message.reply_to_message.from_user:
        return False
    if not client.me:
        return False
    if message.reply_to_message.from_user.username != client.me.username:
        return False
    return True


async def mention_me_filter_func(
    _, client: pyrogram.Client, message: pyrogram.types.Message
) -> bool:
    if not message.text:
        return False
    if client.me.username in message.text:
        return True
    return False


base_filter = filters.create(base_filter_func)
reply_me_filter = filters.create(reply_me_filter_func)
mention_me_filter = filters.create(mention_me_filter_func)
