import re

import httpx
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import Message

from kmua import common, database, i18n


@Client.on_message(
    filters.regex(r"b23.tv/[a-zA-Z0-9]+|bili2233.cn/[a-zA-Z0-9]+"), group=0
)
async def bililink_convert(client: Client, message: Message):
    chat = message.chat
    in_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    chat_config = await database.get_chat_config(chat.id) if in_group else None
    if in_group and not chat_config.convert_b23_enabled:
        return
    if not message.text:
        return
    b23link = re.search(r"(?:b23\.tv|bili2233\.cn)/([a-zA-Z0-9]+)", message.text)
    if not b23link or b23link.group() is None:
        return
    b23code = b23link.group().split("/")[-1]
    if not b23code or len(b23code) != 7:
        return
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(
            f"https://b23.tv/{b23link.group().split('/')[-1]}",
        )
        real_url = resp.headers.get("location")
        if not real_url:
            return
        real_url = real_url.split("?")[0]
    if in_group:
        user = message.sender_chat or message.from_user
        text = i18n.t("bot.msg.b23_converted_group", locale=chat_config.lang).format(
            real_url=real_url, from_user=(await common.mention_html(user))
        )
    else:
        user_config = await database.get_user_config(message.from_user.id)
        text = i18n.t("bot.msg.b23_converted", locale=user_config.lang).format(
            real_url=real_url
        )
    await message.reply_text(text, parse_mode=ParseMode.HTML)
    if in_group:
        try:
            await message.delete()
        except Exception:
            pass
