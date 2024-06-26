import pickle
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common, dao
from kmua.logger import logger

_enable_search = common.meili_client is not None and common.redis_client is not None


async def search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    chat = update.effective_chat
    if not dao.get_chat_message_search_enabled(chat):
        await update.effective_message.reply_text("本群没有开启搜索功能哦")
        return
    if not context.args:
        await update.effective_message.reply_text("请提供要搜索的内容")
        return
    query = " ".join(context.args)
    logger.info(f"[{chat.title}]({update.effective_user.name}) search: {query}")
    try:
        result = common.meili_client.index(f"kmua_{chat.id}").search(
            query,
            {
                "attributesToCrop": ["text"],
                "cropLength": 30,
                "offset": 0,
                "limit": 10,
            },
        )
    except Exception as e:
        logger.error(f"search error: {e.__class__.__name__}: {e}")
        await update.effective_message.reply_text("出错了喵, 搜索失败")
        return
    if not result.get("hits"):
        await update.effective_message.reply_text("没有在本群找到相关内容呢")
        return
    chat_id_str = str(chat.id).removeprefix("-100")
    text = ""
    for hit in result["hits"]:
        emoji = "💬"
        match hit["type"]:
            case common.MessageType.PHOTO.value:
                emoji = "🖼️"
            case common.MessageType.VIDEO.value:
                emoji = "🎥"
            case common.MessageType.AUDIO.value:
                emoji = "🎵"
            case common.MessageType.FILE.value:
                emoji = "📄"
        message_link = f"https://t.me/c/{chat_id_str}/{hit['message_id']}"
        formatted_text = hit["_formatted"]["text"].replace("\n\n", "\n")
        text += f"{escape_markdown(emoji,2)} [{escape_markdown(formatted_text,2)}]({message_link})\n\n"
    uuid = uuid4()
    common.redis_client.set(f"kmua_cqdata_{uuid}", query, ex=6000)
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "下一页",
                    callback_data=f"message_search {uuid} {10}",
                ),
            ]
        ]
    )
    await update.effective_message.reply_text(
        f"找到约 {result['estimatedTotalHits']} 条结果 耗时 {result['processingTimeMs']}ms:\n\n{text}",
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


async def search_message_page(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.callback_query.answer(
            "该功能全局已停用", show_alert=True, cache_time=60
        )
        return
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name}) <search message page>"
    )
    query_uuid, offset = update.callback_query.data.split(" ")[1:]
    query: bytes = common.redis_client.get(f"kmua_cqdata_{query_uuid}")
    if not query:
        await update.callback_query.answer("查询已过期", show_alert=True, cache_time=60)
        return
    query = query.decode("utf-8")
    common.redis_client.expire(f"kmua_cqdata_{query_uuid}", 6000)
    offset = int(offset)
    try:
        result = common.meili_client.index(f"kmua_{update.effective_chat.id}").search(
            query,
            {
                "attributesToCrop": ["text"],
                "cropLength": 30,
                "offset": offset,
                "limit": 10,
            },
        )
    except Exception as e:
        logger.error(f"search error: {e.__class__.__name__}: {e}")
        await update.callback_query.answer(
            "出错了喵, 搜索失败", show_alert=True, cache_time=60
        )
        return
    if not result.get("hits"):
        await update.callback_query.answer("没有更多结果了", cache_time=60)
        return
    chat_id_str = str(update.effective_chat.id).removeprefix("-100")
    text = ""
    for hit in result["hits"]:
        emoji = "💬"
        match hit["type"]:
            case common.MessageType.PHOTO.value:
                emoji = "🖼️"
            case common.MessageType.VIDEO.value:
                emoji = "🎥"
            case common.MessageType.AUDIO.value:
                emoji = "🎵"
            case common.MessageType.FILE.value:
                emoji = "📄"
        message_link = f"https://t.me/c/{chat_id_str}/{hit['message_id']}"
        formatted_text = hit["_formatted"]["text"].replace("\n\n", "\n")
        text += f"{escape_markdown(emoji,2)} [{escape_markdown(formatted_text,2)}]({message_link})\n\n"
    reply_markup = (
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "下一页",
                        callback_data=f"message_search {query_uuid} {offset+10}",
                    ),
                ]
            ]
        )
        if offset == 0
        else InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "上一页",
                        callback_data=f"message_search {query_uuid} {offset-10}",
                    ),
                    InlineKeyboardButton(
                        "下一页",
                        callback_data=f"message_search {query_uuid} {offset+10}",
                    ),
                ]
            ]
        )
    )
    await update.callback_query.edit_message_text(
        f"找到约 {result['estimatedTotalHits']} 条结果 耗时 {result['processingTimeMs']}ms:\n\n{text}",
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


async def enable_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"[{chat.title}]({user.name}) <enable search>")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await update.effective_message.reply_text("你没有权限哦")
        return
    try:
        common.meili_client.create_index(
            f"kmua_{chat.id}", {"primaryKey": "message_id"}
        )
        common.meili_client.index(f"kmua_{chat.id}").update_searchable_attributes(
            ["text"]
        )
    except Exception as e:
        logger.error(f"create index error: {e.__class__.__name__}: {e}")
        await update.effective_message.reply_text("出错了喵, 启用失败")
        return
    dao.update_chat_message_search_enabled(chat, True)
    await update.effective_message.reply_text("已开启搜索功能")


async def disable_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"[{chat.title}]({user.name}) <disable search>")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await update.effective_message.reply_text("你没有权限哦")
        return
    for job in context.job_queue.get_jobs_by_name(f"update_index_{chat.id}"):
        job.schedule_removal()
    dao.update_chat_message_search_enabled(chat, False)
    await update.effective_message.reply_text(
        "已关闭搜索功能, 要删除此前的索引嘛?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "删除", callback_data="delete_search_index confirm"
                    ),
                    InlineKeyboardButton(
                        "保留", callback_data="delete_search_index cancel"
                    ),
                ]
            ]
        ),
    )


async def delete_search_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.callback_query.answer(
            "该功能全局已停用", show_alert=True, cache_time=60
        )
        return
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"[{chat.title}]({user.name}) <delete search index>")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    delete = update.callback_query.data.split()[-1] == "confirm"
    enabled = dao.get_chat_message_search_enabled(chat)
    if delete:
        if enabled:
            await update.callback_query.edit_message_text(
                "当前搜索功能启用中, 请再次执行 /disable_search 哦"
            )
            return
        try:
            common.redis_client.delete(f"kmua_chatmsg_{chat.id}")
            common.meili_client.delete_index(f"kmua_{chat.id}")
        except Exception as e:
            logger.error(f"delete index error: {e.__class__.__name__}: {e}")
            await update.callback_query.edit_message_text(
                "出错了喵, 删除失败", reply_markup=None
            )
            return
        await update.callback_query.edit_message_text(
            "已关闭搜索功能并删除此前的索引数据"
        )
    else:
        await update.callback_query.edit_message_text(
            "已关闭搜索功能, 此前的索引数据保留"
        )


async def update_index(context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Start updating index for {context.job.chat_id}")
    msg_cache = common.redis_client.lrange(f"kmua_chatmsg_{context.job.chat_id}", 0, -1)
    if not msg_cache:
        return
    context.chat_data["updating_index"] = True
    try:
        messages: list[common.MessageInMeili] = [
            pickle.loads(msg).to_dict() for msg in msg_cache
        ]
        common.meili_client.index(f"kmua_{context.job.chat_id}").add_documents(messages)
        common.redis_client.delete(f"kmua_chatmsg_{context.job.chat_id}")
    except Exception as e:
        logger.error(f"load message error: {e.__class__.__name__}: {e}")
        return
    logger.info(f"Index updated for {context.job.chat_id}")
    context.chat_data["updating_index"] = False
