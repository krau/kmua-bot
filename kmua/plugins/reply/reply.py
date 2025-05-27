import random

import pyrogram
import zhconv
from pyrogram import filters

from kmua import database, i18n, resources


async def base_filter_func(_, __, message: pyrogram.types.Message) -> bool:
    if not message.text:
        return False
    if len(message.text) <= 1 or len(message.text) > 1024:
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


@pyrogram.Client.on_message(
    base_filter & (reply_me_filter | filters.private | mention_me_filter),
    group=0,
)
async def word_reply(client: pyrogram.Client, message: pyrogram.types.Message):
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
    for keyword, replies in resources.word_dict.items():
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
