import re

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from ..logger import logger


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_chat.type == "private":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请在群聊中使用哦"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    message = update.effective_message
    this_user = this_user = (
        message.sender_chat if message.sender_chat else message.from_user
    )
    try:
        this_user_mention = this_user.mention_markdown()
    except TypeError:
        this_user_mention = (
            f"[{escape_markdown(this_user.title)}](tg://user?id={this_user.id})"
        )
    replied_user = None
    replied_message = None
    custom_title = " ".join(context.args) if context.args else None
    user_id = this_user.id
    if message.reply_to_message:
        replied_message = message.reply_to_message
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
{this_user_mention} 把 {replied_user.mention_markdown()} 变成{custom_title} !
            """
        text = (
            f"好, 你现在是{custom_title}啦"
            if not replied_message
            else text_when_have_replied_message
        )
        # 在中英文之间加入空格
        text = re.sub(r"([a-zA-Z])([\u4e00-\u9fa5])", r"\1 \2", text)
        text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z])", r"\1 \2", text)

        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest as e:
        if e.message == "Not enough rights":
            text = "咱没有足够的权限"
        elif e.message == "Can't remove chat owner":
            text = "咱不能对群主使用喵"
        elif e.message == "Chat_admin_required":
            text = "咱只能更改由咱自己设置的管理员的头衔"
        elif e.message == "Can't promote self":
            text = "咱不能更改自己的头衔喵"
        else:
            text = f"失败了喵: {e.message}"
            logger.error(f"{e.message}")
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text=text
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        raise e
