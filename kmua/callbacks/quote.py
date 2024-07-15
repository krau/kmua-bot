import asyncio
import random
import re
from math import ceil

from telegram import (
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultsButton,
    Message,
    Update,
    User,
)
from telegram.constants import ChatAction, ChatType
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common, dao
from kmua.logger import logger

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
    if chat.type == ChatType.PRIVATE:
        return
    if context.args and context.args[0] != "nopin":
        return
    if not message.reply_to_message:
        await message.reply_text("请回复一条消息")
        return
    if message.is_topic_message:
        await message.reply_text("暂不支持在主话题外使用此功能")
        return
    quote_message = message.reply_to_message
    quote_user = common.get_message_origin(quote_message)
    qer_user = message.sender_chat or user
    dao.add_user(quote_user)
    quote_message_link = common.get_message_common_link(quote_message)
    if not quote_message_link:
        await message.reply_text("Error: 无法获取消息链接\n本群组可能不是超级群组")
        return
    if dao.get_quote_by_link(quote_message_link):
        sent_message = await message.reply_markdown_v2(
            "这条消息已经在语录中了哦\n_This message will be deleted in 10s_"
        )
        context.job_queue.run_once(
            delete_message,
            10,
            data={"message_id": sent_message.id},
            chat_id=chat.id,
        )
        return
    text = ["好!", "让我康康是谁在说怪话!", "名入册焉"]
    tasks = [
        quote_message.reply_text(text=random.choice(text)),
        _generate_and_send_quote_img(update, context, quote_message, quote_user),
    ]
    chat_config = dao.get_chat_config(chat)
    if (
        not (context.args and context.args[0] == "nopin")
        and chat_config.quote_pin_message
    ):
        tasks.append(_pin_quote_message(quote_message))
    results = await asyncio.gather(*tasks)
    dao.add_quote(
        chat=chat,
        user=quote_user,
        qer=qer_user,
        message=quote_message,
        link=quote_message_link,
        img=results[1],
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


async def _generate_and_send_quote_img(
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
    avatar = await common.get_big_avatar_bytes(quote_user.id, context)
    if not avatar:
        with open(common.DEFAULT_BIG_AVATAR_PATH, "rb") as f:
            avatar = f.read()
    _, quote_img = await asyncio.gather(
        update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO),
        common.generate_quote_img(
            avatar=avatar,
            text=quote_message.text,
            name=quote_user.title if isinstance(quote_user, Chat) else quote_user.name,
        ),
    )
    sent_photo = await update.effective_chat.send_photo(photo=quote_img)
    return sent_photo.photo[0].file_id


async def set_quote_probability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置本群的 random quote 的概率
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name})" + f" {message.text}")

    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await message.reply_text("你没有权限哦")
        return
    except_text = "概率是小于1的小数哦\n如果设置为负则会禁用 /qrand 命令"
    if not context.args:
        await message.reply_text(except_text)
        return
    float_pattern = re.compile(r"^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$")
    value = context.args[0]
    if not float_pattern.match(value) or len(value) > 8:
        await message.reply_text("请不要输入奇怪的东西> <")
        return
    try:
        probability = float(value)
    except Exception:
        await message.reply_text(except_text)
        return
    if probability > 1:
        await message.reply_text(except_text)
        return
    dao.update_chat_quote_probability(chat, probability)
    await message.reply_text(
        text=f"将本聊天的 random quote 的概率设为{probability}啦",
    )


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


async def random_quote(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    随机发送一条语录
    此功能不会在私聊中被调用, 已由 filters 过滤
    私聊中的消息将直接由 keyword_reply_handler 处理
    """
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    logger.trace(f"[{chat.title}]({user.name}) <random_quote>")
    pb = dao.get_chat_quote_probability(chat)
    flag = common.random_unit(pb)
    if message.text is not None:
        if message.text.startswith("/qrand") and pb >= 0:
            flag = True
    if not flag:
        return
    quote = dao.get_chat_random_quote(chat)
    if not quote:
        return
    try:
        sent_message = await chat.forward_to(
            chat_id=chat.id,
            message_id=quote.message_id,
            message_thread_id=update.effective_message.message_thread_id,
        )
        logger.info(f"Bot forward message: {sent_message.text}")
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")


async def delete_quote_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    响应 /d 命令
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not update.callback_query:
        logger.info(f"[{chat.title}]({user.name})" + f" {message.text}")
    query_data = ""
    if update.callback_query:
        query_data = update.callback_query.data
    user_can_manage_bot = await common.verify_user_can_manage_bot_in_chat(
        user, chat, update, context
    )
    if (not message.reply_to_message and user_can_manage_bot) or (
        "chat_quote_manage" in query_data and user_can_manage_bot
    ):
        await _chat_quote_manage(update, context)
        return
    quote_message = message.reply_to_message
    if not quote_message:
        await message.reply_text("请回复要从语录中删除的消息")
        return
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

    message_id = quote_message.id
    chat_id = chat.id
    link = common.get_message_common_link(quote_message)
    if "delete_quote_in_chat" in query_data:
        link = query_data.split(" ")[1]
        chat_id, message_id = common.parse_message_link(link)

    await _unpin_messsage(message_id, chat_id, context)
    if dao.delete_quote_by_link(link):
        if not update.callback_query:
            await quote_message.reply_text("已删除该语录")
        else:
            await asyncio.gather(
                update.callback_query.answer("已删除该语录", show_alert=False),
                _chat_quote_manage(update, context),
            )
    else:
        sent_message = await quote_message.reply_markdown_v2(
            "这条消息不在语录中哦\n_This message will be deleted in 10s_"
        )
        context.job_queue.run_once(
            delete_message,
            10,
            data={"message_id": sent_message.id},
            chat_id=chat.id,
        )


async def _chat_quote_manage(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    分页管理本群的语录
    此功能只应该在 verify_user_can_manage_bot_in_chat 通过时被调用
    """
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"[{chat.title}]({user.name}) <chat_quote_manage>")
    message = update.effective_message
    page = (
        int(update.callback_query.data.split(" ")[-1]) if update.callback_query else 1
    )
    quotes = dao.get_chat_quotes_page(
        chat=update.effective_chat, page=page, page_size=common.QUOTE_PAGE_SIZE
    )
    quotes_count = dao.get_chat_quotes_count(chat)
    max_page = ceil(quotes_count / common.QUOTE_PAGE_SIZE)
    if quotes_count == 0 and not update.callback_query:
        await message.reply_text("本群还没有语录哦")
        return
    if quotes_count == 0 and update.callback_query:
        await update.callback_query.edit_message_text("已经没有语录啦")
        return
    if (page > max_page or page < 1) and update.callback_query:
        await update.callback_query.answer("已经没有啦", show_alert=False, cache_time=5)
        return
    text = (
        f"共有 {quotes_count} 条语录; 当前页: {page}/{max_page}\n点击序号删除语录\n\n"
    )
    keyboard, line = [], []
    for index, quote in enumerate(quotes):
        quote_content = (
            escape_markdown(quote.text[:150], 2)
            if quote.text
            else r"A non\-text message sent by "
            f"{escape_markdown(quote.user.full_name,2)}"
        )
        text += (
            rf"{index+1}\. " f"[{quote_content}]({escape_markdown(quote.link,2)})\n\n"
        )
        line.append(
            InlineKeyboardButton(
                index + 1,
                callback_data=f"delete_quote_in_chat {quote.link} {str(page)}",
            )
        )
    keyboard.append(line)
    navigation_buttons = [
        InlineKeyboardButton(
            "上一页",
            callback_data=f"chat_quote_manage {page - 1}",
        ),
        InlineKeyboardButton(
            f"第{page}/{max_page}页",
            callback_data="chat_quote_page_jump 1",
        ),
        InlineKeyboardButton(
            "下一页",
            callback_data=f"chat_quote_manage {page + 1}",
        ),
    ]
    keyboard.append(navigation_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    if not update.callback_query:
        await message.reply_markdown_v2(
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return
    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
        parse_mode="MarkdownV2",
    )


async def chat_quote_page_jump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    语录管理页数跳转
    """
    user = update.effective_user
    chat = update.effective_chat
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    logger.info(f"[{chat.title}]({user.name})" + f" {update.callback_query.data}")
    quotes_count = dao.get_chat_quotes_count(chat)
    if quotes_count == 0:
        await update.callback_query.edit_message_text("已经没有语录啦")
        return
    quote_page_count = ceil(quotes_count / common.QUOTE_PAGE_SIZE)
    page_jump_page = int(update.callback_query.data.split(" ")[-1])
    page_jump_max_page = ceil(quote_page_count / common.PAGE_JUMP_SIZE)

    if page_jump_page < 1 or page_jump_page > page_jump_max_page:
        await update.callback_query.answer("已经没有啦", show_alert=False, cache_time=5)
        return

    keyboard, line = [], []
    for quote_page in range(
        (page_jump_page - 1) * common.PAGE_JUMP_SIZE + 1,
        (
            page_jump_page * common.PAGE_JUMP_SIZE + 1
            if page_jump_page * common.PAGE_JUMP_SIZE < quote_page_count
            else quote_page_count + 1
        ),
    ):
        if len(keyboard) == 4:
            break
        line.append(
            InlineKeyboardButton(
                quote_page,
                callback_data=f"chat_quote_manage {quote_page}",
            )
        )
        if len(line) == 5:
            keyboard.append(line)
            line = []
    if line:
        keyboard.append(line)
    navigation_buttons = [
        InlineKeyboardButton(
            "上一页",
            callback_data=f"chat_quote_page_jump {page_jump_page - 1}",
        ),
        InlineKeyboardButton(
            f"第{page_jump_page}/{page_jump_max_page}页",
            callback_data="chat_quote_page_jump 1",
        ),
        InlineKeyboardButton(
            "下一页",
            callback_data=f"chat_quote_page_jump {page_jump_page + 1}",
        ),
    ]
    keyboard.append(navigation_buttons)
    text = f"共有 {quotes_count} 条语录, {quote_page_count} 页\n点击页码跳转\n\n"
    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


_result_button = InlineQueryResultsButton(
    text="语录管理", start_parameter="user_quote_manage"
)


async def inline_query_quote(update: Update, _: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.inline_query.query
    logger.debug(f"{user.name} query: {query}")
    results = []
    quotes = dao.query_quote_user_can_see_by_text(user=user, text=query, limit=50)
    for quote in quotes:
        if quote.img:
            results.append(common.get_inline_query_result_cached_photo(quote))
        results.append(common.get_inline_query_result_article(quote))
        if len(results) >= 50:
            break
    await update.inline_query.answer(
        results=results[:49],
        cache_time=5,
        button=_result_button,
        is_personal=True,
    )
