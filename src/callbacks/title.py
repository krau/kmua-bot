from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if update.effective_chat.type == "private":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请在群聊中使用哦"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    this_user = update.effective_user
    this_message = update.effective_message
    replied_user = None
    replied_message = None
    custom_title = context.args[0] if context.args else None
    user_id = this_user.id
    if this_message.reply_to_message:
        replied_message = this_message.reply_to_message
        replied_user = replied_message.from_user
        user_id = replied_user.id
        if not custom_title:
            custom_title = (
                replied_user.username
                if replied_user.username
                else replied_user.full_name
            )
    if not custom_title:
        custom_title = this_user.username if this_user.username else this_user.full_name
    try:
        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id, user_id=user_id, can_manage_chat=True
        )
        await context.bot.set_chat_administrator_custom_title(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            custom_title=custom_title,
        )
        if replied_message:
            text_when_have_replied_message = f"""
{this_user.mention_markdown()}把{replied_user.mention_markdown()}变成{custom_title}!
            """
        text = (
            f"好, 你现在是{custom_title}啦"
            if not replied_message
            else text_when_have_replied_message
        )
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="咱没有足够的权限"
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")
