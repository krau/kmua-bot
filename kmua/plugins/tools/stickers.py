import mimetypes
from io import BytesIO
from typing import BinaryIO

import pyrogram

from kmua import common
from kmua.config import app_config


@pyrogram.Client.on_message(
    pyrogram.filters.sticker & pyrogram.filters.private, group=0
)
async def handle_sticker(client: pyrogram.Client, message: pyrogram.types.Message):
    sticker = message.sticker
    if not sticker:
        return
    ext = mimetypes.guess_extension(sticker.mime_type) or ".png"
    if ext == ".webp":
        ext = ".png"
    if file_id := await common.memttlcache.get(
        f"sticker_file:{sticker.file_unique_id}"
    ):
        await message.reply_document(
            document=file_id,
            force_document=True,
            file_name=f"{sticker.set_name}_{sticker.file_unique_id}.{ext}",
        )
        return
    await message.reply_chat_action(pyrogram.enums.ChatAction.UPLOAD_DOCUMENT)
    file = await client.download_media(sticker, in_memory=True)
    if not file or not isinstance(file, (str, BinaryIO, BytesIO)):
        return
    msg = await message.reply_document(
        document=file,
        force_document=True,
        file_name=f"{sticker.set_name}_{sticker.file_unique_id}.{ext}",
    )
    if msg.document and msg.document.file_id:
        await common.memttlcache.set(
            f"sticker_file:{sticker.file_unique_id}",
            msg.document.file_id,
            ttl=app_config.cachettl_sticker_fileid,  # type: ignore[union-attr]
        )
