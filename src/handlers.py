from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .callbacks.bnhhsh import bnhhsh
from .callbacks.help import help
from .callbacks.interact import interact
from .callbacks.keyword_reply import keyword_reply
from .callbacks.others import chat_migration
from .callbacks.quote import (
    clear_chat_quote,
    clear_chat_quote_ask,
    clear_chat_quote_cancel,
    del_quote,
    inline_query_quote,
    quote,
    random_quote,
    set_quote_probability,
)
from .callbacks.rank import group_rank
from .callbacks.remake import remake
from .callbacks.start import start
from .callbacks.suicide import suicide
from .callbacks.title import title
from .callbacks.userdata import (
    clear_user_img_quote,
    clear_user_text_quote,
    delete_quote,
    next_page,
    prev_page,
    user_data_manage,
    user_quote_manage,
)
from .filters import (
    bnhhsh_filter,
    help_filter,
    interact_filter,
    keyword_reply_filter,
    mention_bot_filter,
    start_filter,
)
from .logger import logger

start_handler = CommandHandler("start", start, filters=start_filter)
chat_migration_handler = MessageHandler(filters.StatusUpdate.MIGRATE, chat_migration)
title_handler = CommandHandler("t", title, filters=mention_bot_filter)
quote_handler = CommandHandler("q", quote)
set_quote_probability_handler = CommandHandler("setqp", set_quote_probability)
del_quote_handler = CommandHandler("d", del_quote)
clear_chat_quote_ask_handler = CommandHandler("c", clear_chat_quote_ask)
help_handler = CommandHandler("help", help, filters=help_filter)
group_rank_handler = CommandHandler("rank", group_rank)
qrand_handler = CommandHandler("qrand", random_quote)
remake_handler = CommandHandler("remake", remake)
suicide_handler = CommandHandler("suicide", suicide)
start_callback_handler = CallbackQueryHandler(start, pattern="back_home")
clear_chat_quote_handler = CallbackQueryHandler(
    clear_chat_quote, pattern="clear_chat_quote"
)
clear_chat_quote_cancel_handler = CallbackQueryHandler(
    clear_chat_quote_cancel, pattern="cancel_clear_chat_quote"
)

clear_user_img_quote_handler = CallbackQueryHandler(
    clear_user_img_quote, pattern="clear_user_img_quote"
)
clear_user_text_quote_handler = CallbackQueryHandler(
    clear_user_text_quote, pattern="clear_user_text_quote"
)

interact_handler = MessageHandler(filters=interact_filter, callback=interact)
inline_query_handler = InlineQueryHandler(inline_query_quote)
user_data_manage_handler = CallbackQueryHandler(
    user_data_manage, pattern="user_data_manage"
)


user_quote_manage_handler = CallbackQueryHandler(
    user_quote_manage, pattern="user_quote_manage"
)
prev_page_handler = CallbackQueryHandler(prev_page, pattern=r"prev_page")
next_page_handler = CallbackQueryHandler(next_page, pattern=r"next_page")
delete_quote_handler = CallbackQueryHandler(delete_quote, pattern=r"delete_quote")
random_quote_handler = MessageHandler(~filters.COMMAND, random_quote)
bnhhsh_handler = MessageHandler(bnhhsh_filter, bnhhsh)
bnhhsh_command_handler = CommandHandler("bnhhsh", bnhhsh)
keyword_reply_handler = MessageHandler(keyword_reply_filter, keyword_reply)
handlers = [
    start_handler,
    chat_migration_handler,
    title_handler,
    quote_handler,
    set_quote_probability_handler,
    del_quote_handler,
    qrand_handler,
    remake_handler,
    suicide_handler,
    start_callback_handler,
    clear_chat_quote_ask_handler,
    help_handler,
    clear_chat_quote_handler,
    group_rank_handler,
    bnhhsh_command_handler,
    clear_chat_quote_cancel_handler,
    interact_handler,
    keyword_reply_handler,
    bnhhsh_handler,
    inline_query_handler,
    user_data_manage_handler,
    user_quote_manage_handler,
    prev_page_handler,
    next_page_handler,
    delete_quote_handler,
    clear_user_img_quote_handler,
    clear_user_text_quote_handler,
    random_quote_handler,
]


async def on_error(update: object | None, context: CallbackContext):
    logger.error(
        f"在该更新发生错误\n{update}\n错误信息\n{context.error.__class__.__name__}:{context.error}"
    )
