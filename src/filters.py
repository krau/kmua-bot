from telegram import Update, Message
from telegram.ext.filters import (
    FilterDataDict,
    UpdateFilter,
    MessageFilter,
)


class StartFilter(UpdateFilter):
    def filter(self, update: Update) -> bool | FilterDataDict | None:
        if (
            update.effective_chat.type != "private"
            and update.effective_message.text == "/start"
        ):
            return False
        return True


class interactFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if message.text.startswith("/") or message.text.startswith("\\"):
            if "bot_command" in message.entities[0].type:
                return False
            return True
        return False


start_filter = StartFilter()
interact_filter = interactFilter()
