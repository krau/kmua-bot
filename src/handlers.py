from .callbacks import start,chat_migration,title
from telegram.ext import (
    CommandHandler,
    filters,
    MessageHandler,
)
from .filters import start_filter

start_handler = CommandHandler("start", start,filters=start_filter)
chat_migration_handler = MessageHandler(filters.StatusUpdate.MIGRATE, chat_migration)
title_handler = CommandHandler('t',title)

handlers = [start_handler, chat_migration_handler,title_handler]
