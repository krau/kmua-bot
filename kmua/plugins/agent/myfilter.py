import pyrogram
from pyrogram import filters
from pyrogram.client import Client

from kmua.common.memory_store import memttlcache
from kmua.config import app_config

_BOTTLE_MSG_PREFIX = "bottle_msg:"
_REPLY_INTENT_PREFIX = "bottle_reply_intent:"


async def base_filter_func(_, __, message: pyrogram.types.Message) -> bool:
    if not message:
        return False
    text = message.text or message.caption or ""
    if (
        message.entities is not None
        and message.entities[0].type == pyrogram.enums.MessageEntityType.BOT_COMMAND
    ):
        return False
    if text.startswith("/") or text.startswith("\\"):
        return False
    return True


async def reply_me_filter_func(
    _, client: Client, message: pyrogram.types.Message
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
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    text = message.text or message.caption or ""
    if not text:
        return False
    if app_config.nickname and app_config.nickname in text:
        return True
    if not client.me:
        return False
    username = client.me.username
    if not username:
        return False
    if username in text:
        return True
    if message.caption and username in message.caption:
        return True
    return False


async def not_bottle_reply_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not message.reply_to_message:
        return True
    reply_to = message.reply_to_message
    if not reply_to.from_user or not client.me:
        return True
    if reply_to.from_user.id != client.me.id:
        return True
    if not reply_to.chat:
        return True
    reply_to_key = f"{_BOTTLE_MSG_PREFIX}{reply_to.chat.id}:{reply_to.id}"
    bottle_data = await memttlcache.get(reply_to_key)
    if not bottle_data:
        return True
    bottle_id = bottle_data.get("bottle_id")
    if not bottle_id:
        return True
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return True
    intent_data = await memttlcache.get(f"{_REPLY_INTENT_PREFIX}{user_id}")
    if intent_data and intent_data.get("bottle_id") == bottle_id:
        return False
    return True


base_filter = filters.create(base_filter_func)
reply_me_filter = filters.create(reply_me_filter_func)
mention_me_filter = filters.create(mention_me_filter_func)
not_bottle_reply_filter = filters.create(not_bottle_reply_filter_func)
