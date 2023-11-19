import asyncio

from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .callbacks import (
    chatdata,
    chatinfo,
    chatmember,
    keyword_reply,
    manage,
    others,
    quote,
    remake,
    slash,
    start,
    sticker,
    userdata,
    title,
    waifu,
    help,
    bilibili,
)
from .filters import (
    keyword_reply_filter,
    mention_or_private_filter,
    slash_filter,
)
from .logger import logger
from .config import settings


# CommandHandlers
start_handler = CommandHandler("start", start.start, filters=mention_or_private_filter)

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

help_handler = CommandHandler("help", help.help, filters=mention_or_private_filter)
error_notice_control_handler = CommandHandler(
    "error_notice", others.error_notice_control
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
refresh_waifu_data_manually_handler = CommandHandler(
    "refresh_waifu_data", manage.refresh_waifu_data_manually
)
status_handler = CommandHandler("status", manage.status)
clear_inactive_user_avatar_handler = CommandHandler(
    "clear_inactive_user_avatar",
    manage.clear_inactive_user_avatar,
    filters=filters.ChatType.PRIVATE,
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


# others
chat_migration_handler = MessageHandler(
    filters.StatusUpdate.MIGRATE, others.chat_migration
)
slash_handler = MessageHandler(slash_filter, slash.slash)
random_quote_handler = MessageHandler(
    (~filters.COMMAND & filters.ChatType.GROUPS), quote.random_quote
)
keyword_reply_handler = MessageHandler(
    keyword_reply_filter, keyword_reply.keyword_reply
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
sticker2img_handler = MessageHandler(
    (filters.Sticker.ALL & filters.ChatType.PRIVATE), sticker.sticker2img
)
chat_title_update_handler = MessageHandler(
    filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_TITLE,
    chatdata.chat_title_update,
)
bililink_convert_handler = MessageHandler(
    filters.ChatType.PRIVATE
    & filters.Regex(r"b23.tv/[a-zA-Z0-9]+|bilibili.com/video/[a-zA-Z0-9]+"),
    bilibili.bililink_convert,
)

handlers = [
    # pin handlers
    start_handler,
    track_chats_handler,
    member_left_handler,
    member_join_handler,
    chat_migration_handler,
    chat_title_update_handler,
    # command handlers
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
    refresh_waifu_data_manually_handler,
    status_handler,
    clear_inactive_user_avatar_handler,
    # callback handlers
    user_data_manage_handler,
    user_data_refresh_handler,
    user_quote_manage_handler,
    marry_waifu_handler,
    chat_quote_manage_handler,
    set_title_permissions_callback_handler,
    start_callback_handler,
    remove_waifu_handler,
    slash_handler,
    user_waifu_manage_handler,
    bot_data_refresh_handler,
    status_refresh_handler,
    clear_inactive_user_avatar_confirm_handler,
    # message handlers
    bililink_convert_handler,
    keyword_reply_handler,
    sticker2img_handler,
    random_quote_handler,
]


async def on_error(update, context):
    error = context.error
    # 如果聊天限制了 bot 发送消息, 忽略
    if error.__class__.__name__ == "BadRequest":
        if error.message == "Chat_write_forbidden":
            return
        if error.message == "There is no caption in the message to edit":
            if update.callback_query:
                await update.callback_query.answer(
                    "请使用 /start 重新召出菜单", show_alert=True, cache_time=600
                )  # 更新后菜单发生了变化, 旧的菜单无法使用
            return
        if "Not enough rights to send" in error.message:
            return
    elif error.__class__.__name__ == "Forbidden":
        if "bot was kicked from the supergroup chat" in error.message:
            return
    msg = f"在该更新发生错误\n{update}\n"
    msg += f"错误信息\n{error.__class__.__name__}:{error}"
    logger.error(msg)
    if context.bot_data.get("error_notice", False):

        async def send_update_error(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
            )

        tasks = [send_update_error(chat_id) for chat_id in settings.owners]
        await asyncio.gather(*tasks)
