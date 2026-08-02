import random

import pyrogram
import zhconv
from pyrogram import filters
from pyrogram.client import Client

from kmua import database, i18n, resources
from kmua.common.memory_store import memttlcache
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.services import manyacg

_BOTTLE_MSG_PREFIX = "bottle_msg:"
_REPLY_INTENT_PREFIX = "bottle_reply_intent:"


async def word_reply(client: Client, message: pyrogram.types.Message):
    user = message.from_user
    if not user:
        return
    user_config = await database.get_user_config(user)
    if not message.text or not client.me:
        return
    text = zhconv.convert(
        message.text.replace(client.me.username, "").strip().lower(), "zh-cn"
    )
    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    all_replies = []
    word_dict = resources.get_word_dict()
    for keyword, replies in word_dict.items():
        if keyword in text:
            all_replies.extend(replies)
    if all_replies:
        await message.reply_text(
            text=random.choice(all_replies),
        )
    else:
        await message.reply_text(
            text=i18n.trl("bot.msg.reply.default", locale=user_config.lang)
        )


async def _base_filter_func(_, __, message: pyrogram.types.Message) -> bool:
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


async def _reply_me_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not is_explicit_reply(message):
        return False
    if not message.reply_to_message:
        return False
    if not message.reply_to_message.from_user:
        return False
    if not client.me:
        return False
    if message.reply_to_message.from_user.username != client.me.username:
        return False
    return True


async def _mention_me_filter_func(
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


async def _not_bottle_reply_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not is_explicit_reply(message):
        return True
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


_base_filter = filters.create(_base_filter_func)
_reply_me_filter = filters.create(_reply_me_filter_func)
_mention_me_filter = filters.create(_mention_me_filter_func)
_not_bottle_reply_filter = filters.create(_not_bottle_reply_filter_func)


async def _agent_disabled_filter_func(_, __, ___) -> bool:
    return not app_config.agent


_agent_disabled_filter = filters.create(_agent_disabled_filter_func)

_filter = (
    _base_filter
    & (_reply_me_filter | filters.private | _mention_me_filter)
    & _not_bottle_reply_filter
    & ~pyrogram.filters.regex("|".join([r.pattern for r in manyacg.ARTWORK_ALL_REGEX]))
    # WeChat article links are handled by the wechat parser (group -1); the
    # keyword reply must not double-respond to them.
    & ~pyrogram.filters.regex(r"https?://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+")
    # Twitter/X links are handled by the native tweet parser (group -1); the
    # keyword reply must not double-respond to them.
    & ~pyrogram.filters.regex(r"(?:twitter|x)\.com/[^/]+/status/\d+")
)

_chat_command_filter = filters.command("chat") & _not_bottle_reply_filter


@Client.on_message((_filter | _chat_command_filter) & _agent_disabled_filter, group=0)
async def wake_simple_reply(client: Client, message: pyrogram.types.Message):
    return await word_reply(client, message)


__all__ = ["word_reply", "wake_simple_reply"]
