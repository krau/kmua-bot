from telegram.ext import CommandHandler, MessageHandler, filters, InlineQueryHandler

from .callbacks import (
    chat_migration,
    clear_chat_quote,
    del_quote,
    quote,
    random_quote,
    set_quote_probability,
    start,
    title,
    interact,
    inline_query_quote,
)
from .filters import start_filter, interact_filter

start_handler = CommandHandler("start", start, filters=start_filter)
chat_migration_handler = MessageHandler(filters.StatusUpdate.MIGRATE, chat_migration)
title_handler = CommandHandler("t", title)
quote_handler = CommandHandler("q", quote)
set_quote_probability_handler = CommandHandler("setqp", set_quote_probability)
random_quote_handler = MessageHandler(~filters.COMMAND, random_quote)
del_quote_handler = CommandHandler("d", del_quote)
clear_chat_quote_handler = CommandHandler("c", clear_chat_quote)
interact_handler = MessageHandler(filters=interact_filter, callback=interact)
inline_query_handler = InlineQueryHandler(inline_query_quote)
handlers = [
    start_handler,
    chat_migration_handler,
    title_handler,
    quote_handler,
    set_quote_probability_handler,
    del_quote_handler,
    clear_chat_quote_handler,
    interact_handler,
    random_quote_handler,
    inline_query_handler,
]
