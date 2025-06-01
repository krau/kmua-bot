from io import BytesIO
from typing import BinaryIO

import pyrogram


@pyrogram.Client.on_message(
    pyrogram.filters.sticker & pyrogram.filters.private, group=0
)
async def handle_sticker(client: pyrogram.Client, message: pyrogram.types.Message):
    sticker = message.sticker
    if not sticker:
        return
    await message.reply_chat_action(pyrogram.enums.ChatAction.UPLOAD_DOCUMENT)
    file = await client.download_media(sticker, in_memory=True)
    if not file or not isinstance(file, (str, BinaryIO, BytesIO)):
        return
    await message.reply_document(
        document=file,
        force_document=True,
        file_name=f"{sticker.set_name}_{sticker.file_unique_id}.png",
    )
