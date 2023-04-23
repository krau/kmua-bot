from .callbacks import start
from telegram.ext import (
    CommandHandler,
    filters,
    MessageHandler,
)
from .callbacks import chat_migration
from .filters import start_filter

start_handler = MessageHandler(start_filter, start)
chat_migration_handler = MessageHandler(filters.StatusUpdate.MIGRATE, chat_migration)

handlers = [start_handler, chat_migration_handler]
