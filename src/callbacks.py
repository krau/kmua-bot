import random

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .config.config import settings
from .logger import logger
from .utils import generate_quote_img, random_unit


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
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
    if update.effective_message.text == "/t":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text="你要艾特Kmua!",
        )
        logger.info(f"Bot: {update.effective_message.text}")
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
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")


async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if not update.effective_message.reply_to_message:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text="请回复一条消息",
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = update.effective_message.reply_to_message
    await context.bot.pin_chat_message(
        chat_id=update.effective_chat.id, message_id=quote_message.id
    )
    logger.debug(f"Bot将 {quote_message.text} 置顶")
    if not context.chat_data.get("quote_messages", None):
        context.chat_data["quote_messages"] = []
    if quote_message.id not in context.chat_data["quote_messages"]:
        context.chat_data["quote_messages"].append(quote_message.id)
        logger.debug(
            f"将{quote_message.id}([{update.effective_chat.title}]({update.effective_user.name}))"
            + "加入chat quote"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="已入典",
            reply_to_message_id=quote_message.id,
        )
    if not quote_message.text or len(quote_message.text) > 70:
        return
    try:
        avatar = await (
            await (
                await context.bot.get_chat(chat_id=quote_message.from_user.id)
            ).photo.get_big_file()
        ).download_as_bytearray()
        quote_img = await generate_quote_img(
            avatar=avatar, text=quote_message.text, name=quote_message.from_user.name
        )
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=quote_img)
    except AttributeError:
        pass
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")


async def set_quote_probability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_chat.type != "private":
        admins = await context.bot.get_chat_administrators(
            chat_id=update.effective_chat.id
        )
        if (
            update.effective_user.id not in [admin.user.id for admin in admins]
            and update.effective_user.id not in settings["owners"]
        ):
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="你没有权限哦"
            )
            logger.info(f"Bot: {sent_message.text}")
            return
    try:
        probability = float(update.effective_message.text.split(" ")[1])
    except ValueError:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    except IndexError:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请指定概率"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    if probability < 0 or probability > 1:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    context.chat_data["quote_probability"] = probability
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"将本聊天的发典设置概率为{probability}啦",
    )
    logger.info(f"Bot: {sent_message.text}")


async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + (
            f" {update.effective_message.text}"
            if update.effective_message.text
            else "<非文本消息>"
        )
    )
    if not random_unit(context.chat_data.get("quote_probability", 0.1)):
        return
    if not context.chat_data.get("quote_messages", None):
        return
    sent_message = await context.bot.forward_message(
        chat_id=update.effective_chat.id,
        from_chat_id=update.effective_chat.id,
        message_id=random.choice(context.chat_data["quote_messages"]),
    )
    logger.info("Bot: " + (f"{sent_message.text}" if sent_message.text else "<非文本消息>"))


async def del_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if not context.chat_data.get("quote_messages", None):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="该聊天没有典呢"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    if not update.effective_message.reply_to_message:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请回复要移出典的消息"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = update.effective_message.reply_to_message
    if quote_message.id in context.chat_data["quote_messages"]:
        context.chat_data["quote_messages"].remove(quote_message.id)
        logger.debug(
            f"将{quote_message.id}([{update.effective_chat.title}]({update.effective_user.name}))"
            + "移出chat quote"
        )
        await context.bot.unpin_chat_message(
            chat_id=update.effective_chat.id, message_id=quote_message.id
        )
        logger.debug(
            "Bot将"
            + (f"{quote_message.text}" if quote_message.text else "<一条非文本消息>")
            + "取消置顶"
        )
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="已移出典",
            reply_to_message_id=quote_message.id,
        )
        logger.info(f"Bot: {sent_message.text}")
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="该消息不在典中;请对原始的典消息使用",
            reply_to_message_id=quote_message.id,
        )


async def clear_chat_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if not context.chat_data.get("quote_messages", None):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="该聊天没有典呢"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    for message_id in context.chat_data["quote_messages"]:
        try:
            unpin_ok = await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id, message_id=message_id
            )
            if unpin_ok:
                logger.debug(f"Bot将{message_id}取消置顶")
        except Exception as e:
            logger.error(e)
            continue
    context.chat_data["quote_messages"] = []
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text="已清空该聊天的典"
    )
    logger.info(f"Bot: {sent_message.text}")


async def interact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if reply_to_message := update.effective_message.reply_to_message:
        if len(update.effective_message.text.split(" ")) == 1:
            if update.effective_message.text.startswith("/"):
                interact_cmd = update.effective_message.text[1:]
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{update.effective_user.full_name}{interact_cmd}了{reply_to_message.from_user.full_name}!",
                )
                logger.info(f"Bot: {sent_message.text}")
            elif update.effective_message.text.startswith("\\"):
                interact_cmd = update.effective_message.text[1:]
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{update.effective_user.full_name}被{reply_to_message.from_user.full_name}{interact_cmd}了!",
                )
                logger.info(f"Bot: {sent_message.text}")
        else:
            if update.effective_message.text.startswith("/"):
                interact_cmd_front = update.effective_message.text.split(" ")[
                    0
                ].replace("/", "")
                interact_cmd_back = update.effective_message.text.split(" ")[1:]
                interact_cmd_back = " ".join(interact_cmd_back)
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{update.effective_user.full_name}{interact_cmd_front}{reply_to_message.from_user.full_name}{interact_cmd_back}!",
                )
                logger.info(f"Bot: {sent_message.text}")
            elif update.effective_message.text.startswith("\\"):
                interact_cmd_front = update.effective_message.text.split(" ")[
                    0
                ].replace("\\", "")
                interact_cmd_back = update.effective_message.text.split(" ")[1:]
                interact_cmd_back = " ".join(interact_cmd_back)
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{reply_to_message.from_user.full_name}{interact_cmd_front}{update.effective_user.full_name}{interact_cmd_back}!",
                )
                logger.info(f"Bot: {sent_message.text}")
    else:
        if update.effective_message.text.startswith("/"):
            interact_cmd = update.effective_message.text[1:]
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{update.effective_user.full_name}{interact_cmd}了自己!",
            )
            logger.info(f"Bot: {sent_message.text}")
        elif update.effective_message.text.startswith("\\"):
            interact_cmd = update.effective_message.text[1:]
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{update.effective_user.full_name}被自己{interact_cmd}了!",
            )
            logger.info(f"Bot: {sent_message.text}")