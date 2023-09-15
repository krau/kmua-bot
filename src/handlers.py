import asyncio

from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .callbacks.chatinfo import getid
from .callbacks.chatmember import (
    on_member_join,
    on_member_left,
    set_greet,
    track_chats,
)
from .callbacks.help import help
from .callbacks.interact import interact
from .callbacks.keyword_reply import keyword_reply
from .callbacks.others import chat_migration, error_notice_control
from .callbacks.quote import (
    delete_quote_in_chat,
    inline_query_quote,
    quote,
    random_quote,
    set_quote_probability,
)
from .callbacks.remake import remake
from .callbacks.start import start
from .callbacks.sticker import clear_sticker_cache, sticker2img
from .callbacks.title import (
    set_title_permissions,
    set_title_permissions_callback,
    title,
)
from .callbacks.userdata import (
    user_data_manage,
    user_data_refresh,
    user_waifu_manage,
    delete_user_quote,
)
from .callbacks.waifu import marry_waifu, remove_waifu, today_waifu, waifu_graph
from .config import settings
from .filters import (
    interact_filter,
    keyword_reply_filter,
    mention_or_private_filter,
)
from .logger import logger

# CommandHandlers
start_handler = CommandHandler("start", start, filters=mention_or_private_filter)
chat_migration_handler = MessageHandler(filters.StatusUpdate.MIGRATE, chat_migration)
title_handler = CommandHandler("t", title, filters=mention_or_private_filter)

quote_handler = CommandHandler("q", quote, filters=filters.ChatType.GROUPS)
set_quote_probability_handler = CommandHandler(
    "setqp", set_quote_probability, filters=filters.ChatType.GROUPS
)
delete_quote_handler = CommandHandler(
    "d", delete_quote_in_chat, filters=filters.ChatType.GROUPS
)
qrand_handler = CommandHandler("qrand", random_quote, filters=filters.ChatType.GROUPS)

help_handler = CommandHandler("help", help, filters=mention_or_private_filter)
error_notice_control_handler = CommandHandler("error_notice", error_notice_control)
remake_handler = CommandHandler("remake", remake)

today_waifu_handler = CommandHandler(
    "waifu", today_waifu, filters=filters.ChatType.GROUPS
)
waifu_graph_handler = CommandHandler(
    "waifu_graph", waifu_graph, filters=filters.ChatType.GROUPS
)

set_greet_handler = CommandHandler(
    "set_greet", set_greet, filters=filters.ChatType.GROUPS
)

getid_handler = CommandHandler("id", getid)
set_title_permissions_handler = CommandHandler("sett", set_title_permissions)
clear_sticker_cache_handler = CommandHandler("clear_sticker_cache", clear_sticker_cache)

# CallbackQueryHandlers
start_callback_handler = CallbackQueryHandler(start, pattern="back_home")

remove_waifu_handler = CallbackQueryHandler(remove_waifu, pattern="remove_waifu")
user_waifu_manage_handler = CallbackQueryHandler(
    user_waifu_manage, pattern="user_waifu_manage|set_waifu_mention|divorce"
)
set_title_permissions_callback_handler = CallbackQueryHandler(
    set_title_permissions_callback, pattern="set_title_permissions"
)
chat_quote_manage_handler = CallbackQueryHandler(
    delete_quote_in_chat, pattern="chat_quote_manage|delete_quote_in_chat"
)
user_data_manage_handler = CallbackQueryHandler(
    user_data_manage, pattern="user_data_manage"
)
user_data_refresh_handler = CallbackQueryHandler(
    user_data_refresh, pattern="user_data_refresh"
)
marry_waifu_handler = CallbackQueryHandler(marry_waifu, pattern=r".*marry_waifu.*")
user_quote_manage_handler = CallbackQueryHandler(
    delete_user_quote, pattern="user_quote_manage|delete_user_quote"
)


# others
interact_handler = MessageHandler(filters=interact_filter, callback=interact)
inline_query_handler = InlineQueryHandler(inline_query_quote)
random_quote_handler = MessageHandler(~filters.COMMAND, random_quote)
keyword_reply_handler = MessageHandler(keyword_reply_filter, keyword_reply)
track_chats_handler = ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER)
member_left_handler = MessageHandler(
    filters.StatusUpdate.LEFT_CHAT_MEMBER, on_member_left
)
member_join_handler = MessageHandler(
    filters.StatusUpdate.NEW_CHAT_MEMBERS, on_member_join
)
sticker2img_handler = MessageHandler(
    (filters.Sticker.ALL & filters.ChatType.PRIVATE), sticker2img
)

handlers = [
    start_handler,
    track_chats_handler,
    member_left_handler,
    member_join_handler,
    chat_migration_handler,
    today_waifu_handler,
    waifu_graph_handler,
    quote_handler,
    user_data_manage_handler,
    user_data_refresh_handler,
    user_quote_manage_handler,
    marry_waifu_handler,
    title_handler,
    set_quote_probability_handler,
    qrand_handler,
    remake_handler,
    delete_quote_handler,
    chat_quote_manage_handler,
    set_greet_handler,
    set_title_permissions_handler,
    clear_sticker_cache_handler,
    set_title_permissions_callback_handler,
    start_callback_handler,
    help_handler,
    getid_handler,
    error_notice_control_handler,
    interact_handler,
    remove_waifu_handler,
    keyword_reply_handler,
    inline_query_handler,
    user_waifu_manage_handler,
    sticker2img_handler,
    random_quote_handler,
]


async def on_error(update: object | None, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    # 如果聊天限制了 bot 发送消息, 忽略
    if error.__class__.__name__ == "BadRequest":
        if error.message == "Chat_write_forbidden":
            return
    logger.error(f"在该更新发生错误\n{update}\n错误信息\n{error.__class__.__name__}:{error}")
    if context.bot_data.get("error_notice", False):

        async def send_update_error(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"在该更新发生错误\n{update}\n错误信息\n\n{context.error.__class__.__name__}:{context.error}",
            )

        tasks = [send_update_error(chat_id) for chat_id in settings.owners]
        await asyncio.gather(*tasks)
