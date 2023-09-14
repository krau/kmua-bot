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
from telegram.constants import ChatAction, ChatType
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
    verify_user_can_manage_bot,
    verify_user_is_chat_admin,
    get_message_common_link,
)
from .jobs import delete_message


async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    响应 /q 命令
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name})" + f" {message.text}")

    await message_recorder(update, context)

    if chat.type == ChatType.PRIVATE:
        return
    if context.args:
        return
    if not message.reply_to_message:
        sent_message = await message.reply_text("请回复一条消息")
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = message.reply_to_message
    quote_user = quote_message.from_user
    forward_from_user = quote_message.forward_from or quote_message.forward_from_chat
    if forward_from_user:
        quote_user = forward_from_user
    if quote_message.sender_chat:
        quote_user = quote_message.sender_chat
    qer_user = user
    if message.sender_chat:
        qer_user = message.sender_chat
    quote_message_link = get_message_common_link(quote_message)
    if dao.get_quote_by_link(quote_message_link):
        sent_message = await message.reply_markdown_v2(
            "这条消息已经在语录中了哦" "\n_This message will be deleted in 10s_"
        )
        logger.info(f"Bot: {sent_message.text}")
        context.job_queue.run_once(
            delete_message,
            10,
            data={"message_id": sent_message.id},
            chat_id=chat.id,
        )
        return

    await _pin_quote_message(quote_message)

    await quote_message.reply_text(text="好!")

    quote_img_file_id = await _generate_and_sned_quote_img(
        update, context, quote_message, quote_user
    )
    await _save_quote_data(
        update, qer_user, quote_message, quote_user, quote_img_file_id
    )


async def _pin_quote_message(quote_message: Message) -> bool:
    """
    将消息置顶, 忽略异常

    :param quote_message: 要置顶的消息
    :return: 是否置顶成功
    """
    try:
        return await quote_message.pin(disable_notification=True)
    except Exception:
        return False


async def _generate_and_sned_quote_img(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    quote_message: Message,
    quote_user: User | Chat,
) -> str | None:
    """
    生成并发送语录图片

    :param update: Update
    :param context: Context
    :param quote_message: 消息
    :param quote_user: 消息发送者
    :return: 若生成成功, 返回图片的 file_id, 否则返回 None
    """
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
    qer: User | Chat,
    quote_message: Message,
    quote_user: User | Chat,
    quote_img: str | None,
) -> None:
    """
    保存语录数据

    :param update: Update
    :param qer: 语录的记录者
    :param quote_message: 语录消息
    :param quote_user: 语录消息的发送者
    :param quote_img: 语录图片的 file_id
    """
    dao.add_quote(
        chat=update.effective_chat,
        user=quote_user,
        qer=qer,
        message=quote_message,
        img=quote_img,
    )


async def set_quote_probability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置本群的 random quote 的概率
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name})" + f" {message.text}")
    await message_recorder(update, context)

    if not await verify_user_is_chat_admin(user, chat, context):
        return
    except_text = "概率是在[0,1]之间的浮点数,请检查输入"
    try:
        probability = float(context.args[0])
    except Exception:
        sent_message = await message.reply_text(except_text)
        logger.info(f"Bot: {sent_message.text}")
        return
    if probability < 0 or probability > 1:
        sent_message = await message.reply_text(except_text)
        logger.info(f"Bot: {sent_message.text}")
        return
    dao.set_chat_quote_probability(chat, probability)
    sent_message = await message.reply_text(
        text=f"将本聊天的 random quote 的概率设为{probability}啦",
    )
    logger.info(f"Bot: {sent_message.text}")


async def _unpin_messsage(
    message_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    取消置顶消息, 忽略异常

    :param message_id: 消息 id
    :param chat_id: 聊天 id
    :param context: Context
    """
    try:
        return await context.bot.unpin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        return False


async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    随机发送一条语录
    此功能不会在私聊中被调用, 已由 filters 过滤
    私聊中的消息将直接由 keyword_reply_handler 处理
    """
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    logger.info(
        f"[{chat.title}({chat.id})]<{user.name}({user.id})>"
        + (f" {message.text}" if message.text else "<非文本消息>")
    )
    await message_recorder(update, context)

    pb = dao.get_chat_quote_probability(chat)
    flag = random_unit(pb)
    if message.text is not None:
        if message.text.startswith("/qrand"):
            flag = True
    if not flag:
        return
    quotes = dao.get_chat_quotes(chat)
    if not quotes:
        return
    quote = random.choice(quotes)
    message_id = quote.message_id
    try:
        sent_message = await chat.forward_to(
            chat_id=chat.id,
            message_id=message_id,
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        dao.delete_quote(quote)
        await _unpin_messsage(message_id, chat.id, context)


async def delete_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    响应 /d 命令
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name})" + f" {message.text}")
    await message_recorder(update, context)

    user_can_manage_bot = await verify_user_can_manage_bot(user, chat, update, context)
    if not message.reply_to_message and user_can_manage_bot:
        await _chat_quote_manage(update, context)
        return
    quote_message = message.reply_to_message
    quote_user = quote_message.sender_chat or quote_message.from_user

    user = message.sender_chat if message.sender_chat else user
    if user.id != quote_user.id and not user_can_manage_bot:
        sent_message = await message.reply_markdown_v2(
            "你只能删除自己的语录哦\n_This message will be deleted in 10s_"
        )
        logger.info(f"Bot: {sent_message.text}")
        context.job_queue.run_once(
            delete_message,
            10,
            data={"message_id": sent_message.id},
            chat_id=chat.id,
        )
        return
    await _unpin_messsage(quote_message.id, chat.id, context)
    if dao.delete_chat_quote_by_message_id(chat, quote_message.id):
        sent_message = await quote_message.reply_text("已删除该语录")
        logger.info(f"Bot: {sent_message.text}")
    else:
        sent_message = await quote_message.reply_markdown_v2(
            "这条消息不在语录中哦\n_This message will be deleted in 10s_"
        )
        logger.info(f"Bot: {sent_message.text}")
        context.job_queue.run_once(
            delete_message,
            10,
            data={"message_id": sent_message.id},
            chat_id=chat.id,
        )


async def _chat_quote_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    分页管理本群的语录
    此功能只应该在 verify_user_can_manage_bot 通过时被调用
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    page = 1
    page_size = 10
    quotes = dao.get_chat_quotes_page(
        chat=update.effective_chat, page=page, page_size=page_size
    )
    if not quotes:
        sent_message = await message.reply_text("本群没有语录哦")
        logger.info(f"Bot: {sent_message.text}")
        return
    quotes_count = dao.get_chat_quotes_count(chat)
    max_page = quotes_count // page_size + 1
    text = f"共有 {quotes_count} 条语录; 当前页: {page}/{max_page}\n\n"
    for quote in quotes:
        text += f"{quote.message_id} {quote.text}\n"


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
