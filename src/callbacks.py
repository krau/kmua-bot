from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from .logger import logger


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        update.effective_chat.type != "private"
        and update.effective_message.text == "/start"
    ):
        return
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text="喵喵喵?"
    )
    logger.info(f"Bot:{sent_message.text}")
    await context.bot.send_sticker(
        chat_id=update.effective_chat.id,
        sticker="CAACAgEAAxkBAAIKWGREi3q4O_H40T66DbTZGyNAf0CbAALPAAN92oBFKGj8op00zJ8vBA",
    )

async def chat_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    application = context.application
    application.migrate_chat_data(message=message)