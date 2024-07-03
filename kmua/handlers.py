import asyncio

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

import kmua.filters as kmua_filters
from kmua import dao

from .callbacks import (
    bilibili,
    chatdata,
    chatinfo,
    chatmember,
    delete_events,
    help,
    image,
    ip,
    manage,
    pin,
    quote,
    remake,
    reply,
    search,
    setu,
    slash,
    start,
    sticker,
    title,
    userdata,
    waifu,
)
from .logger import logger

# CommandHandlers
start_handler = CommandHandler(
    "start", start.start, filters=kmua_filters.mention_or_private_filter
)

title_handler = CommandHandler("t", title.title, filters=filters.ChatType.GROUPS)

quote_handler = CommandHandler("q", quote.quote, filters=filters.ChatType.GROUPS)
set_quote_probability_handler = CommandHandler(
    "setqp", quote.set_quote_probability, filters=filters.ChatType.GROUPS
)
delete_quote_handler = CommandHandler(
    "d", quote.delete_quote_in_chat, filters=filters.ChatType.GROUPS
)
qrand_handler = CommandHandler(
    "qrand", quote.random_quote, filters=filters.ChatType.GROUPS
)

help_handler = CommandHandler(
    "help", help.help, filters=kmua_filters.mention_or_private_filter
)
error_notice_control_handler = CommandHandler(
    "error_notice", manage.error_notice_control, filters=filters.ChatType.PRIVATE
)
remake_handler = CommandHandler("remake", remake.remake)

today_waifu_handler = CommandHandler(
    "waifu", waifu.today_waifu, filters=filters.ChatType.GROUPS
)
waifu_graph_handler = CommandHandler(
    "waifu_graph", waifu.waifu_graph, filters=filters.ChatType.GROUPS
)

set_greet_handler = CommandHandler(
    "set_greet", chatmember.set_greet, filters=filters.ChatType.GROUPS
)

getid_handler = CommandHandler("id", chatinfo.getid)
set_title_permissions_handler = CommandHandler(
    "sett", title.set_title_permissions, filters=filters.ChatType.GROUPS
)
chat_data_manage_handler = CommandHandler(
    "manage", chatdata.chat_data_manage, filters=filters.ChatType.GROUPS
)
bot_manage_handler = CommandHandler(
    "manage", manage.manage, filters=filters.ChatType.PRIVATE
)
set_bot_admin_in_chat_handler = CommandHandler(
    "set_bot_admin", manage.set_bot_admin_in_chat, filters=filters.ChatType.GROUPS
)
set_bot_admin_globally_handler = CommandHandler(
    "set_bot_admin", manage.set_bot_admin_globally, filters=filters.ChatType.PRIVATE
)
leave_chat_handler = CommandHandler("leave_chat", manage.leave_chat)
clean_data_data_manually_handler = CommandHandler(
    "clean_data", manage.clean_data_manually
)
status_handler = CommandHandler("status", manage.status)
clear_inactive_user_avatar_handler = CommandHandler(
    "clear_inactive_user_avatar",
    manage.clear_inactive_user_avatar,
    filters=filters.ChatType.PRIVATE,
)
setu_handler = CommandHandler("setu", setu.setu)
switch_waifu_handler = CommandHandler(
    "switch_waifu", waifu.switch_waifu, filters=filters.ChatType.GROUPS
)
switch_delete_events_handler = CommandHandler(
    "switch_delete_events",
    delete_events.switch_delete_events,
    filters=filters.ChatType.GROUPS,
)
ip_handler = CommandHandler("ip", ip.ipinfo)
refresh_user_data_by_id_handler = CommandHandler(
    "refresh", userdata.refresh_user_data_by_id
)
switch_unpin_channel_pin_handler = CommandHandler(
    "switch_unpin_channel_pin",
    pin.switch_unpin_channel_pin,
    filters=filters.ChatType.GROUPS,
)
reset_contents_handler = CommandHandler("reset_contents", reply.reset_contents)
fix_quotes_handler = CommandHandler("fix_quotes", manage.fix_quotes)
fix_chats_handler = CommandHandler("fix_chats", manage.fix_chats)
enable_search_handler = CommandHandler(
    "enable_search", search.enable_search, filters=filters.ChatType.GROUPS
)
disable_search_handler = CommandHandler(
    "disable_search", search.disable_search, filters=filters.ChatType.GROUPS
)
message_search_handler = CommandHandler(
    "search", search.search_message, filters=filters.ChatType.GROUPS
)
import_history_handler = CommandHandler(
    "import_history", search.import_history, filters=filters.ChatType.GROUPS
)
update_index_handler = CommandHandler(
    "update_index", search.update_index, filters=filters.ChatType.GROUPS
)
index_stats_handler = CommandHandler("index_stats", search.index_stats)
clear_all_contents_handler = CommandHandler(
    "clear_all_contents", reply.clear_all_contents
)
sr_handler = CommandHandler(
    "sr", image.super_resolute, filters=~filters.UpdateType.EDITED
)

# CallbackQueryHandlers
start_callback_handler = CallbackQueryHandler(start.start, pattern="back_home")
remove_waifu_handler = CallbackQueryHandler(waifu.remove_waifu, pattern="remove_waifu")
user_waifu_manage_handler = CallbackQueryHandler(
    userdata.user_waifu_manage, pattern="user_waifu_manage|set_waifu_mention|divorce"
)
set_title_permissions_callback_handler = CallbackQueryHandler(
    title.set_title_permissions_callback, pattern="set_title_permissions"
)
chat_quote_manage_handler = CallbackQueryHandler(
    quote.delete_quote_in_chat, pattern="chat_quote_manage|delete_quote_in_chat"
)
chat_quote_page_jump_handler = CallbackQueryHandler(
    quote.chat_quote_page_jump, pattern="chat_quote_page_jump"
)
user_data_manage_handler = CallbackQueryHandler(
    userdata.user_data_manage, pattern="user_data_manage"
)
user_data_refresh_handler = CallbackQueryHandler(
    userdata.user_data_refresh, pattern="user_data_refresh"
)
marry_waifu_handler = CallbackQueryHandler(
    waifu.marry_waifu, pattern=r".*marry_waifu.*"
)
user_quote_manage_handler = CallbackQueryHandler(
    userdata.delete_user_quote,
    pattern="user_quote_manage|delete_user_quote|qer_quote_manage",
)
bot_data_refresh_handler = CallbackQueryHandler(
    manage.bot_data_refresh, pattern="bot_data_refresh"
)
status_refresh_handler = CallbackQueryHandler(manage.status, pattern="status_refresh")
clear_inactive_user_avatar_confirm_handler = CallbackQueryHandler(
    manage.clear_inactive_user_avatar, pattern="clear_inactive_user_avatar"
)
delete_search_index_handler = CallbackQueryHandler(
    search.delete_search_index, pattern="delete_search_index"
)
message_search_page_handler = CallbackQueryHandler(
    search.search_message_page, pattern="message_search"
)


# MessageHandlers
slash_handler = MessageHandler(
    kmua_filters.slash_filter & ~filters.UpdateType.EDITED, slash.slash
)
bililink_convert_handler = MessageHandler(
    filters.ChatType.PRIVATE
    & filters.Regex(r"b23.tv/[a-zA-Z0-9]+|bilibili.com/video/[a-zA-Z0-9]+"),
    bilibili.bililink_convert,
)
random_quote_handler = MessageHandler(
    (~filters.COMMAND & filters.ChatType.GROUPS), quote.random_quote
)
reply_handler = MessageHandler(
    (~filters.COMMAND & kmua_filters.reply_filter & ~filters.UpdateType.EDITED),
    reply.reply,
)
sticker2img_handler = MessageHandler(
    (filters.Sticker.ALL & filters.ChatType.PRIVATE), sticker.sticker2img
)
delete_event_message_handler = MessageHandler(
    (kmua_filters.service_message_filter & filters.ChatType.SUPERGROUP),
    delete_events.delete_event_message,
)
unpin_channel_pin_handler = MessageHandler(
    kmua_filters.auto_forward_filter, pin.unpin_channel_pin
)

# others
chat_migration_handler = MessageHandler(
    filters.StatusUpdate.MIGRATE, chatdata.chat_migration
)
track_chats_handler = ChatMemberHandler(
    chatmember.track_chats, ChatMemberHandler.MY_CHAT_MEMBER
)
member_left_handler = MessageHandler(
    filters.StatusUpdate.LEFT_CHAT_MEMBER, chatmember.on_member_left
)
member_join_handler = MessageHandler(
    filters.StatusUpdate.NEW_CHAT_MEMBERS, chatmember.on_member_join
)
chat_title_update_handler = MessageHandler(
    filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_TITLE,
    chatdata.chat_title_update,
)
inline_query_handler = InlineQueryHandler(quote.inline_query_quote)


callback_query_handlers = [
    user_data_manage_handler,
    user_data_refresh_handler,
    user_quote_manage_handler,
    marry_waifu_handler,
    chat_quote_manage_handler,
    chat_quote_page_jump_handler,
    set_title_permissions_callback_handler,
    start_callback_handler,
    remove_waifu_handler,
    user_waifu_manage_handler,
    bot_data_refresh_handler,
    status_refresh_handler,
    clear_inactive_user_avatar_confirm_handler,
    delete_search_index_handler,
    message_search_page_handler,
]

command_handlers = [
    start_handler,
    today_waifu_handler,
    waifu_graph_handler,
    quote_handler,
    chat_data_manage_handler,
    title_handler,
    set_quote_probability_handler,
    qrand_handler,
    remake_handler,
    delete_quote_handler,
    set_greet_handler,
    set_title_permissions_handler,
    help_handler,
    getid_handler,
    error_notice_control_handler,
    bot_manage_handler,
    set_bot_admin_in_chat_handler,
    set_bot_admin_globally_handler,
    leave_chat_handler,
    clean_data_data_manually_handler,
    status_handler,
    clear_inactive_user_avatar_handler,
    setu_handler,
    switch_waifu_handler,
    switch_delete_events_handler,
    ip_handler,
    refresh_user_data_by_id_handler,
    switch_unpin_channel_pin_handler,
    reset_contents_handler,
    fix_quotes_handler,
    fix_chats_handler,
    enable_search_handler,
    disable_search_handler,
    message_search_handler,
    import_history_handler,
    update_index_handler,
    index_stats_handler,
    clear_all_contents_handler,
    sr_handler,
]

chatdata_handlers = [
    track_chats_handler,
    member_left_handler,
    member_join_handler,
    chat_migration_handler,
    chat_title_update_handler,
]

message_handlers = [
    bililink_convert_handler,
    reply_handler,
    slash_handler,
    sticker2img_handler,
    delete_event_message_handler,
    unpin_channel_pin_handler,
    random_quote_handler,
]

inline_query_handler_group = [inline_query_handler]


async def on_error(update: Update, context):
    """
    出现未被处理的错误时回调
    """
    error = context.error
    # 如果聊天限制了 bot 发送消息, 忽略
    if error.__class__.__name__ == "BadRequest":
        if "Chat_write_forbidden" in error.message:
            return
        if "There is no caption in the message to edit" in error.message:
            if update.callback_query:
                await update.callback_query.answer(
                    "请使用 /start 重新召出菜单", show_alert=True, cache_time=600
                )  # 更新后菜单发生了变化, 旧的菜单无法使用
            return
        if "Message is not modified" in error.message:
            if update.callback_query:
                await update.callback_query.answer(
                    "请...请慢一点> <", show_alert=True, cache_time=1
                )
            return
        if (
            "Not enough rights to send" in error.message
            or "Message to be replied not found" in error.message
        ):
            return
    elif error.__class__.__name__ == "TimedOut":
        logger.warning(f"Timeout error\n{update}")
        return
    elif error.__class__.__name__ == "Forbidden":
        if "bot was kicked from the supergroup chat" in error.message:
            return
    msg = f"在该更新发生错误\n{update}\n"
    msg += f"错误信息\n{error.__class__.__name__}:{error}"
    logger.error(msg)
    if context.bot_data.get("error_notice", True):

        async def send_update_error(chat_id):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                )
            except Exception as e:
                logger.error(f"发送错误信息失败\n{e}")

        await asyncio.gather(
            *(send_update_error(admin.id) for admin in dao.get_bot_global_admins())
        )
