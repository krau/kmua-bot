import random
import time
from uuid import uuid4

from telegram import (
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultsButton,
    InputTextMessageContent,
    Message,
    Update,
    User,
)
from telegram.constants import ChatAction, ChatID
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from ..config.config import settings
from ..database import dao
from ..logger import logger
from ..utils import (
    generate_quote_img,
    get_big_avatar_bytes,
    message_recorder,
    random_unit,
    fake_users_id,
)


async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if context.args:
        return
    if not update.effective_message.reply_to_message:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text="请回复一条消息",
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = update.effective_message.reply_to_message
    quote_user = quote_message.from_user
    forward_from_user = quote_message.forward_from
    # is_chat = False
    # is_bot = False
    if forward_from_user:
        quote_user = forward_from_user
    if quote_message.sender_chat:
        quote_user = quote_message.sender_chat
        # is_chat = True
    # if not is_chat:
    #     if quote_user.is_bot:
    #         is_bot = True
    # not_user = is_chat or is_bot or quote_user.id in [fake_users_id]
    await _pin_quote_message(quote_message)

    await quote_message.reply_text(text="好!")

    quote_img_file_id = await _generate_and_sned_quote_img(
        update, context, quote_message, quote_user
    )
    await _save_quote_data(update, quote_message, quote_user, quote_img_file_id)


async def _pin_quote_message(quote_message: Message):
    try:
        await quote_message.pin(disable_notification=True)
    except Exception:
        pass


async def _generate_and_sned_quote_img(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    quote_message: Message,
    quote_user: User | Chat,
) -> str | None:
    if not quote_message.text:
        return None
    if len(quote_message.text) > 200:
        return None
    avatar = await get_big_avatar_bytes(quote_user.id, context)
    if not avatar:
        return None
    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
    quote_img = await generate_quote_img(
        avatar=avatar,
        text=quote_message.text,
        name=quote_user.title if isinstance(quote_user, Chat) else quote_user.name,
    )
    sent_photo = await update.effective_chat.send_photo(photo=quote_img)
    return sent_photo.photo[0].file_id


async def _save_quote_data(
    update: Update,
    quote_message: Message,
    quote_user: User | Chat,
    quote_img: str | None,
):
    dao.add_quote(
        chat=update.effective_chat,
        user=quote_user,
        message_id=quote_message.id,
        text=quote_message.text,
        img=quote_img,
    )


async def set_quote_probability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
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
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"  # noqa: E501
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
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"  # noqa: E501
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    context.chat_data["quote_probability"] = probability
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"将本聊天的名言提醒设置概率为{probability}啦",
    )
    logger.info(f"Bot: {sent_message.text}")


async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    this_chat = update.effective_chat
    this_user = update.effective_user
    this_message = update.effective_message
    logger.info(
        f"[{this_chat.title}]({this_user.name if this_user else None})"
        + (f" {this_message.text}" if this_message.text else "<非文本消息>")
    )
    await message_recorder(update, context)
    probability = context.chat_data.get("quote_probability", 0.001)
    probability = float(probability)
    flag = random_unit(probability)
    if update.effective_message.text is not None:
        if update.effective_message.text.startswith("/qrand"):
            flag = True
    if not flag:
        return
    if not context.chat_data.get("quote_messages", None):
        return
    try:
        to_forward_message_id: int = random.choice(context.chat_data["quote_messages"])
        sent_message = await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=update.effective_chat.id,
            message_id=to_forward_message_id,
        )
        logger.info(
            "Bot: " + (f"{sent_message.text}" if sent_message.text else "<非文本消息>")
        )
    except BadRequest:
        logger.error(f"{to_forward_message_id} 未找到,从chat quote中移除")
        context.chat_data["quote_messages"].remove(to_forward_message_id)
    except Exception as e:
        logger.error(f"{e.__class__.__name__}: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )


async def del_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if not context.chat_data.get("quote_messages", None):
        sent_message = await update.effective_message.reply_text("该聊天没有名言呢")
        logger.info(f"Bot: {sent_message.text}")
        return
    if update.effective_message.reply_to_message:
        await _del_a_quote(update, context)
        return
    all_quote_messages = context.chat_data["quote_messages"]
    chat_id = update.effective_chat.id
    chat_id = str(chat_id).removeprefix("-100")
    prefix = f"https://t.me/c/{chat_id}/"
    all_quote_messages_link = [
        prefix + str(message_id) for message_id in all_quote_messages
    ]
    total = len(all_quote_messages_link)
    if total <= 10:
        text = "\n\n".join(all_quote_messages_link)
        sent_message = await update.effective_message.reply_text(
            text=text, disable_web_page_preview=True, allow_sending_without_reply=True
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    current_page = 1
    max_page = total // 10 + 1
    text = f"共记录 {total} 条; 当前页: {current_page}/{max_page}\n\n" + "\n\n".join(
        all_quote_messages_link[:10]
    )
    sent_message = await update.effective_message.reply_text(
        text=text,
        disable_web_page_preview=True,
        allow_sending_without_reply=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "上一页",
                        callback_data=f"del_quote_page {current_page - 1}",
                    ),
                    InlineKeyboardButton(
                        "下一页",
                        callback_data=f"del_quote_page {current_page + 1}",
                    ),
                ]
            ]
        ),
    )
    logger.info(f"Bot: {sent_message.text}")


async def del_quote_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_page = int(update.callback_query.data.split(" ")[-1])
    all_quote_messages = context.chat_data["quote_messages"]
    chat_id = update.effective_chat.id
    chat_id = str(chat_id).removeprefix("-100")
    prefix = f"https://t.me/c/{chat_id}/"
    all_quote_messages_link = [
        prefix + str(message_id) for message_id in all_quote_messages
    ]
    total = len(all_quote_messages_link)
    max_page = total // 10 + 1
    if current_page < 1:
        current_page = 1
    if current_page > max_page:
        current_page = max_page
    text = f"共记录 {total} 条; 当前页: {current_page}/{max_page}\n\n" + "\n\n".join(
        all_quote_messages_link[(current_page - 1) * 10 : current_page * 10]
    )
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text=text,
        message_id=update.callback_query.message.id,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "上一页",
                        callback_data=f"del_quote_page {current_page - 1}",
                    ),
                    InlineKeyboardButton(
                        "下一页",
                        callback_data=f"del_quote_page {current_page + 1}",
                    ),
                ]
            ]
        ),
    )


async def _del_a_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quote_message = update.effective_message.reply_to_message
    if quote_message.id in context.chat_data["quote_messages"]:
        context.chat_data["quote_messages"].remove(quote_message.id)
        logger.debug(
            f"将{quote_message.id}([{update.effective_chat.title}]({update.effective_user.name}))"
            + "移出chat quote"
        )
        try:
            await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id, message_id=quote_message.id
            )
            logger.debug(
                "Bot将"
                + (
                    f"{quote_message.text}"
                    if quote_message.text
                    else "<一条非文本消息>"  # noqa: E501
                )  # noqa: E501
                + "取消置顶"
            )
        except Exception as e:
            logger.error(f"{e.__class__.__name__}: {e}")
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="已移出语录",
            reply_to_message_id=quote_message.id,
        )
        logger.info(f"Bot: {sent_message.text}")
    else:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="该消息不在语录中;请对原始的名言消息使用\n或直接使用 /d 管理本群语录",
            reply_to_message_id=quote_message.id,
        )
        logger.info(f"Bot: {sent_message.text}")


_clear_chat_quote_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("算了", callback_data="cancel_clear_chat_quote"),
            InlineKeyboardButton("确认清空", callback_data="clear_chat_quote"),
        ]
    ]
)


async def clear_chat_quote_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if not context.chat_data.get("quote_messages", None):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="该聊天没有名言呢"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    if update.effective_chat.type != "private":
        this_chat_member = await update.effective_chat.get_member(
            update.effective_user.id
        )
        if this_chat_member.status != "creator":
            await update.effective_message.reply_text("你没有权限哦")
            return
    sent_message = await update.message.reply_text(
        text="真的要清空该聊天的语录吗?\n\n用户个人数据不会被此操作清除",
        reply_markup=_clear_chat_quote_markup,
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_chat_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if (
            update.effective_user.id
            != update.callback_query.message.reply_to_message.from_user.id
        ):
            await context.bot.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="你没有权限哦",
                show_alert=True,
            )
            return
    if not context.chat_data.get("quote_messages", None):
        return
    edited_message = await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text="正在清空...",
        message_id=update.callback_query.message.id,
    )
    for message_id in context.chat_data["quote_messages"]:
        try:
            unpin_ok = await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id, message_id=message_id
            )
            if unpin_ok:
                logger.debug(f"Bot将{message_id}取消置顶")
        except BadRequest:
            continue
        except Exception as e:
            logger.error(e)
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
            )
            time.sleep(0.5)
            continue
    context.chat_data["quote_messages"] = []
    sent_message = await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text="已清空该聊天的语录",
        message_id=edited_message.id,
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_chat_quote_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if (
            update.effective_user.id
            != update.callback_query.message.reply_to_message.from_user.id
        ):
            await context.bot.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="你没有权限哦",
                show_alert=True,
            )
            return
    await update.callback_query.message.delete()


_result_button = InlineQueryResultsButton(text="名言管理", start_parameter="start")


async def inline_query_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    user_id = update.inline_query.from_user.id
    quotes_data = context.bot_data["quotes"].get(user_id, {})
    text_quotes = quotes_data.get("text", [])
    img_quotes = quotes_data.get("img", [])
    is_personal = True
    cache_time = 10
    results = []
    no_quote_inline_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "看看我的", url=f"https://t.me/{context.bot.username}?start=start"
                )
            ]
        ]
    )
    if not text_quotes and not img_quotes:
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="你还没有保存任何名言",
                input_message_content=InputTextMessageContent("我还没有任何名言"),
                reply_markup=no_quote_inline_markup,
            )
        )
    else:
        if query:
            for text_quote in text_quotes:
                if query in text_quote["content"]:
                    create_at_str = text_quote["created_at"].strftime(
                        "%Y年%m月%d日%H时%M分%S秒"
                    )  # noqa: E501
                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=text_quote["content"],
                            input_message_content=InputTextMessageContent(
                                text_quote["content"]
                            ),
                        )
                    )
            for img_quote in img_quotes:
                if query in img_quote["text"]:
                    create_at_str = img_quote["created_at"].strftime(
                        "%Y年%m月%d日%H时%M分%S秒"
                    )  # noqa: E501
                    results.append(
                        InlineQueryResultCachedPhoto(
                            id=str(uuid4()),
                            photo_file_id=img_quote["content"],
                        )
                    )
            if len(results) == 0:
                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="没有找到相关名言",
                        input_message_content=InputTextMessageContent(
                            message_text=f"我没有说过有 *{escape_markdown(query)}* 的名言!",  # noqa: E501
                            parse_mode="Markdown",
                        ),
                        reply_markup=no_quote_inline_markup,
                    )
                )
        else:
            results = []
            for text_quote in random.sample(text_quotes, min(len(text_quotes), 10)):
                create_at_str = text_quote["created_at"].strftime(
                    "%Y年%m月%d日%H时%M分%S秒"
                )  # noqa: E501
                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title=text_quote["content"],
                        input_message_content=InputTextMessageContent(
                            message_text=text_quote["content"],
                        ),
                        description=f"于{create_at_str}记",
                    )
                )

            for img_quote in random.sample(img_quotes, min(len(img_quotes), 10)):
                create_at_str = img_quote["created_at"].strftime(
                    "%Y年%m月%d日%H时%M分%S秒"
                )  # noqa: E501
                results.append(
                    InlineQueryResultCachedPhoto(
                        id=str(uuid4()),
                        photo_file_id=img_quote["content"],
                    )
                )
    await update.inline_query.answer(
        button=_result_button,
        results=results,
        is_personal=is_personal,
        cache_time=cache_time,
    )


async def clear_user_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    user_id = update.effective_user.id
    if user_id not in settings.owners:
        return
    try:
        to_clear_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("请输入数字")
        return
    except IndexError:
        await update.effective_message.reply_text("请输入要清除的用户id")
        return
    if to_clear_id not in context.bot_data["quotes"].keys():
        await update.effective_message.reply_text("该用户没有名言")
        return
    context.bot_data["quotes"].pop(to_clear_id)
    await context.application.persistence.flush()
    await update.effective_message.reply_text("已清除该用户的名言")
