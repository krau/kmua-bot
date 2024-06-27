import pickle
import tempfile
from typing import Any, Generator
from uuid import uuid4

import orjson
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
            query, _get_search_params()
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
    for hit_text in _get_hit_text(result["hits"], chat_id_str):
        text += hit_text
    if not text:
        await update.callback_query.answer("没有更多结果了", cache_time=60)
        return
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
            "该功能已全局停用", show_alert=True, cache_time=60
        )
        return
    if not dao.get_chat_message_search_enabled(update.effective_chat):
        await update.callback_query.answer(
            "该功能在本群已停用", show_alert=True, cache_time=60
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
            query, _get_search_params(offset)
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
    for hit_text in _get_hit_text(result["hits"], chat_id_str):
        text += hit_text
    if not text:
        await update.callback_query.answer("没有更多结果了", cache_time=60)
        return
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
                        f"第 {offset//10+1} 页",
                        callback_data="noop",
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
        common.meili_client.index(f"kmua_{chat.id}").update_filterable_attributes(
            ["type", "user_id"]
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
            context.chat_data.pop("pending_messages", None)
            await context.application.persistence.flush()
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


async def import_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    chat = update.effective_chat
    if not dao.get_chat_message_search_enabled(chat):
        await update.effective_message.reply_text("本群没有开启搜索功能哦")
        return
    if context.chat_data.get("updating_index"):
        await update.effective_message.reply_text("正在更新索引, 请稍后再试")
        return
    if not await common.verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        await update.effective_message.reply_text("你没有权限哦")
        return

    logger.info(f"[{chat.title}]({update.effective_user.name}) <import history>")
    message = update.effective_message
    target_message = message.reply_to_message
    if (
        not target_message
        or not target_message.document
        or target_message.document.mime_type != "application/json"
    ):
        await message.reply_text("请回复一个导出的json历史记录文件")
        return
    if target_message.document.file_size > 20 * 1024 * 1024:
        await message.reply_text("太大了, 不行!")
        return

    if context.chat_data.get("importing_history"):
        await update.effective_message.reply_text("太快了, 不行!")
        return
    context.chat_data["importing_history"] = True
    try:
        history_file = await target_message.document.get_file()

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/{chat.id}_history.json"
            await history_file.download_to_drive(file_path)
            with open(file_path, "r") as f:
                history_raw: dict[str, Any] = orjson.loads(f.read())

        if not history_raw:
            await message.reply_text("导入失败, 请检查文件格式")
            return

        chat_id = "-100" + str(history_raw["id"])
        if chat_id != str(chat.id):
            await message.reply_text("导入失败, 文件中的历史记录不属于此群")
            return
        if history_raw["type"] not in ("private_supergroup", "public_supergroup"):
            await message.reply_text("导入失败, 非超级群组历史记录")
            return
        history_raw_messages: list = history_raw.get("messages")
        if not history_raw_messages:
            await message.reply_text("文件中没有消息记录")
            return

        await message.reply_text(f"正在导入历史消息, 共 {len(history_raw_messages)} 条")

        count = 0
        for msg in _get_message_meili(history_raw_messages):
            count += 1
            if context.chat_data.get("updating_index"):
                if not context.chat_data.get("pending_messages"):
                    context.chat_data["pending_messages"] = []
                context.chat_data["pending_messages"].append(msg)
                continue
            common.redis_client.rpush(f"kmua_chatmsg_{chat.id}", pickle.dumps(msg))
        await target_message.reply_text(f"已将 {count} 条消息加入队列, 请稍等更新哦")
    except Exception as e:
        logger.error(f"import history error: {e.__class__.__name__}: {e}")
        await message.reply_text("出错了喵, 导入失败")
    finally:
        context.chat_data["importing_history"] = False


async def update_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not common.verify_user_can_manage_bot(update.effective_user):
        return
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    chat = update.effective_chat
    if not dao.get_chat_message_search_enabled(chat):
        await update.effective_message.reply_text("本群没有开启搜索功能哦")
        return
    if context.chat_data.get("updating_index"):
        await update.effective_message.reply_text("正在更新索引, 请稍后再试")
        return
    logger.info(f"[{chat.title}]({update.effective_user.name}) <update index>")
    context.job_queue.run_once(
        update_index_job,
        0,
        chat_id=chat.id,
        name=f"update_index_{chat.id}",
    )
    await update.effective_message.reply_text("更新本群索引")


async def index_stats(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        await update.effective_message.reply_text("没有接入这个功能哦")
        return
    if common.verify_user_can_manage_bot(update.effective_user):
        try:
            all_stats = common.meili_client.get_all_stats()
            await update.effective_message.reply_text(
                f"数据库大小: {all_stats['databaseSize'] / 1024 / 1024:.2f}MB\n"
                f"已索引对话: {len(all_stats['indexes'])} 个\n"
                f"最后更新时间: {all_stats['lastUpdate']}"
            )
        except Exception as e:
            logger.error(f"get index stats error: {e.__class__.__name__}: {e}")
            await update.effective_message.reply_text("出错了喵, 获取失败")
        return
    chat = update.effective_chat
    if chat.type not in (chat.SUPERGROUP, chat.GROUP):
        return
    try:
        index_stats = common.meili_client.index(f"kmua_{chat.id}").get_stats()
        await update.effective_message.reply_text(
            f"本群已索引 {index_stats.number_of_documents} 条消息"
        )
    except Exception as e:
        logger.error(f"get index stats error: {e.__class__.__name__}: {e}")
        await update.effective_message.reply_text("出错了喵, 获取失败")
        return


async def update_index_job(context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get("updating_index"):
        logger.debug(f"index is updating for {context.job.chat_id}, skip")
    msg_cache = common.redis_client.lrange(f"kmua_chatmsg_{context.job.chat_id}", 0, -1)
    if not msg_cache:
        logger.debug(f"no message to update for {context.job.chat_id}")
        return
    logger.debug(f"updating index for {context.job.chat_id}")
    context.chat_data["updating_index"] = True
    try:
        messages: list[common.MessageInMeili] = [
            pickle.loads(msg).to_dict() for msg in msg_cache
        ]
        logger.debug(f"load {len(messages)} messages for {context.job.chat_id}")
        common.meili_client.index(f"kmua_{context.job.chat_id}").add_documents(messages)
        common.redis_client.delete(f"kmua_chatmsg_{context.job.chat_id}")
    except Exception as e:
        logger.error(f"load message error: {e.__class__.__name__}: {e}")
        return
    finally:
        context.chat_data["updating_index"] = False
    logger.info(f"Index updated for {context.job.chat_id}")


def _get_message_meili(
    raw_messages: list,
) -> Generator[common.MessageInMeili, None, None]:
    for msg_export in raw_messages:
        if msg_export["type"] != "message":
            continue
        if not msg_export.get("full_text") or not msg_export.get("text_entities"):
            continue
        is_bot_command = False
        for entity in msg_export["text_entities"]:
            if entity["type"] == "bot_command":
                is_bot_command = True
                break
        if is_bot_command:
            continue
        try:
            from_id: str = msg_export.get("from_id")
            if from_id.startswith("user"):
                from_id = int(from_id.removeprefix("user"))
            elif from_id.startswith("channel"):
                from_id = int(f"-100{from_id.removeprefix('channel')}")
            else:
                continue
            message_id = int(msg_export["id"])
        except ValueError:
            logger.warning(
                f"invalid message id or from_id: {msg_export['id']}, {msg_export['from_id']}"
            )
            continue
        message_type = common.MessageType.TEXT
        full_text = msg_export["full_text"]
        media_type = msg_export.get("media_type")
        if media_type != "sticker" and msg_export.get("mime_type") != "image/webp":
            match media_type:
                case "voice_message" | "audio_file":
                    message_type = common.MessageType.AUDIO
                case "video_file":
                    message_type = common.MessageType.VIDEO
                case _:
                    file_name = msg_export.get("file_name")
                    if file_name:
                        message_type = common.MessageType.FILE
                        full_text += f" {file_name}"
        if msg_export.get("photo"):
            message_type = common.MessageType.PHOTO
        full_text += f" {msg_export.get("title", "")}"
        yield common.MessageInMeili(
            message_id=message_id,
            user_id=from_id,
            text=full_text,
            type=message_type,
        )


def _get_message_type_emoji(type: int) -> str:
    match type:
        case common.MessageType.PHOTO.value:
            return "🖼️"
        case common.MessageType.VIDEO.value:
            return "🎥"
        case common.MessageType.AUDIO.value:
            return "🎵"
        case common.MessageType.FILE.value:
            return "📄"
        case _:
            return "💬"


def _get_hit_text(hits: list[dict], chat_id: str) -> Generator[str, None, None]:
    for hit in hits:
        if hit["_rankingScore"] <= 0.1:
            # TODO: meilisearch 1.9 之后将会支持 rankingScoreThreshold 参数, 可在请求时直接过滤
            break
        emoji = _get_message_type_emoji(hit["type"])
        message_link = f"https://t.me/c/{chat_id}/{hit['message_id']}"
        formatted_text = hit["_formatted"]["text"].replace("\n", " ")
        formatted_text = f"{escape_markdown(emoji,2)} [{escape_markdown(formatted_text,2)}]({message_link})\n\n"
        user_id: int = hit["user_id"]
        if db_user := dao.get_user_by_id(user_id):
            user_text = escape_markdown(f"[{db_user.full_name}]:\n", 2)
        else:
            user_text = escape_markdown(f"[{user_id}]:\n", 2)
        yield f"{user_text}{formatted_text}"


def _get_search_params(offset: int = 0) -> dict:
    return {
        "attributesToCrop": ["text"],
        "cropLength": 30,
        "offset": offset,
        "limit": 10,
        "matchingStrategy": "all",
        "showRankingScore": True,
    }
