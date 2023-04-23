from telegram.ext import MessageHandler, filters
from telegram.ext.filters import MessageFilter, UpdateFilter, ChatType, UpdateType


class StartFilter(UpdateFilter):
    def filter(self, update):
        if (
            update.effective_chat.type != "private"
            and update.effective_message.text == "/start"
        ):
            return False
        return True

start_filter = StartFilter()