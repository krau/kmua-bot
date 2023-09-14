from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from ..config import settings
from ..logger import logger


async def sticker2img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"sticker2img {update.effective_user.name}")
    if update.message.sticker is None:
        return
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT
    )
    sticker = update.message.sticker

    file = None
    ext_name = "png"
    if sticker.file_unique_id in context.bot_data["sticker2img"]:
        file = context.bot_data["sticker2img"][sticker.file_unique_id]
    if not file:
        file = await sticker.get_file()
        file = await file.download_as_bytearray()
        file = bytes(file)
    if sticker.is_animated:
        return
    if sticker.is_video:
        ext_name = "mp4"
    sent_message = await update.message.reply_document(
        document=file,
        filename=f"{sticker.file_size}.{ext_name}",
        disable_content_type_detection=True,
        allow_sending_without_reply=True,
        caption=f"file_id: {sticker.file_id}",
    )
    doc_file_id = sent_message.document.file_id
    context.bot_data["sticker2img"][sticker.file_unique_id] = doc_file_id


async def clear_sticker_cache(update: Update, context: ContextTypes):
    logger.info(f"clear_sticker_cache {update.effective_user.name}")
    if update.effective_user.id not in settings.owners:
        return
    context.bot_data["sticker2img"] = {}
    await update.message.reply_text("清除成功")
