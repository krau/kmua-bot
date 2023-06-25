from telegram import Message
from telegram.ext.filters import (
    FilterDataDict,
    MessageFilter,
)
from telegram.ext import filters
from .utils import random_unit
from .config.config import settings
from .data import word_dict
from zhconv import convert


class InteractFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if len(message.text) <= 1:
            return False
        if message.text.startswith("/") or message.text.startswith("\\"):
            if len(message.entities) == 0:
                return True
            if "bot_command" in message.entities[0].type:
                return False
            return True
        return False


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
        if f"@{message.get_bot().username}" not in message.text:
            return False
        return True


class RandomFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        pr = float(settings.get("random_filter", 0))
        if random_unit(pr):
            return True
        return False


class ReplyBotFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.reply_to_message:
            return False
        if (
            not message.reply_to_message.from_user.username
            == message.get_bot().username
        ):
            return False
        return True


class KeywordReplyFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        message_text = message.text.replace(message.get_bot().username, "").lower()
        message_text = convert(message_text, "zh-cn")
        for keyword in word_dict.keys():
            if keyword in message_text:
                return True
        return False


mention_or_private_filter = MentionBotFilter() | filters.ChatType.PRIVATE
interact_filter = InteractFilter() & TextLengthFilter(min_length=1, max_length=100)
keyword_reply_filter = (
    TextLengthFilter(min_length=1, max_length=200)
    & ~interact_filter
    & KeywordReplyFilter()
) & (ReplyBotFilter() | MentionBotFilter() | filters.ChatType.PRIVATE)
bnhhsh_filter = (
    filters.Regex("[a-zA-Z]")
    & TextLengthFilter(min_length=2, max_length=256)
    & ~keyword_reply_filter
) & (MentionBotFilter() | RandomFilter())
