import asyncio
import datetime
from io import BytesIO

import pyrogram
from wordcloud import WordCloud

from kmua import common, consts, database, i18n


@pyrogram.Client.on_message(pyrogram.filters.command("wordcloud"), group=0)
async def wordcloud_command(client: pyrogram.Client, message: pyrogram.types.Message):
    chat_id = message.chat.id if message.chat else 0
    if not chat_id:
        return
    chat_config = await database.get_chat_config(chat_id)
    if await common.memstore.get(f"wordcloud_gen:{chat_id}"):
        await message.reply_text(
            i18n.t("bot.msg.wordcloud.generating", chat_config.lang)
        )
        return
    await common.memstore.set(f"wordcloud_gen:{chat_id}", True)
    try:
        await message.reply_chat_action(pyrogram.enums.ChatAction.UPLOAD_PHOTO)
        stop_message_id = (
            message.reply_to_message.id if message.reply_to_message else message.id
        )
        historys = await common.get_messages_with_cache(
            chat_id=chat_id,
            message_ids=range(stop_message_id - 200, stop_message_id),
        )
        text = "\n".join(msg.text for msg in historys if msg.text)
        if not text:
            await message.reply_text(
                i18n.t("bot.msg.wordcloud.no_text", chat_config.lang)
            )
            return
        result = await asyncio.to_thread(
            WordCloud(
                font_path=consts.QUOTE_FONT_PATH,
                width=1920,
                height=1080,
                background_color="white"
                if 6 < datetime.datetime.now().hour < 18
                else "black",
            ).generate,
            text,
        )  # type: ignore

        img_bytes = BytesIO()
        result.to_image().save(img_bytes, format="PNG")
        img_bytes.seek(0)
        await message.reply_photo(
            photo=img_bytes,
            caption=i18n.t("bot.msg.wordcloud.generated", chat_config.lang),
        )
    finally:
        await common.memstore.delete(f"wordcloud_gen:{chat_id}")
