from telegram import Message, Update
from telegram.ext.filters import (
    FilterDataDict,
    MessageFilter,
    UpdateFilter,
)
from telegram.ext import filters
from .utils import random_unit
from .config.config import settings


class StartFilter(UpdateFilter):
    def filter(self, update: Update) -> bool | FilterDataDict | None:
        if (
            update.effective_chat.type != "private"
            and update.effective_message.text == "/start"
        ):
            return False
        return True


class InteractFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if message.text.startswith("/") or message.text.startswith("\\"):
            if len(message.entities) == 0:
                return True
            if "bot_command" in message.entities[0].type:
                return False
            return True
        return False


class HelpFilter(UpdateFilter):
    def filter(self, update: Update) -> bool | FilterDataDict | None:
        if (
            update.effective_chat.type != "private"
            and update.effective_message.text == "/help"
        ):
            return False
        return True


class TextLengthFilter(MessageFilter):
    def __init__(
        self,
        name: str = None,
        data_filter: bool = False,
        min_length: int = 2,
        max_length: int = 100,
    ):
        super().__init__(name, data_filter)
        self.min_length = min_length
        self.max_length = max_length

    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if len(message.text) < self.min_length:
            return False
        if len(message.text) > self.max_length:
            return False
        return True


class MentionBotFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if not message.text.startswith(f"@{message.get_bot().username}"):
            return False
        return True


class RandomFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        pr = float(settings.get("random_filter", 0))
        if random_unit(pr):
            return True
        return False


start_filter = StartFilter()
interact_filter = InteractFilter()
help_filter = HelpFilter()
bnhhsh_filter = (
    filters.Regex("[a-zA-Z]") & TextLengthFilter(min_length=2, max_length=256)
) & (filters.ChatType.PRIVATE | MentionBotFilter() | RandomFilter())
