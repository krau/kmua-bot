import random

import pyrogram
import zhconv
from pyrogram.client import Client

from kmua import database, i18n, resources


async def word_reply(client: Client, message: pyrogram.types.Message):
    user = message.from_user
    if not user:
        return
    user_config = await database.get_user_config(user)
    if not message.text or not client.me or not client.me.username:
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
