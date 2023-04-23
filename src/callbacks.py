from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from telegram.error import BadRequest
from .logger import logger


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name}) <call start>"
    )
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
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + "<chat_migration>"
    )
    message = update.message
    application = context.application
    application.migrate_chat_data(message=message)


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name}) <call title>"
    )
    if update.effective_chat.type == "private":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请在群聊中使用哦"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    bot_username = context.bot_data["bot_username"]
    custom_title = update.effective_message.text[len(bot_username) + 4 :]
    if not custom_title:
        custom_title = (
            update.effective_user.username
            if update.effective_user.username
            else update.effective_user.full_name
        )
    try:
        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            can_manage_chat=True,
            can_change_info=True,
            can_manage_video_chats=True,
            can_pin_messages=True,
            can_invite_users=True,
        )
        logger.debug(
            f"Bot将[{update.effective_chat.title}]({update.effective_user.name})设为管理员"
        )
        await context.bot.set_chat_administrator_custom_title(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            custom_title=custom_title,
        )
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text=f"好, 你现在是{custom_title}啦",
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Kmua没有足够的权限"
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")
