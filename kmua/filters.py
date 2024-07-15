from telegram import Message
from telegram.ext import filters
from telegram.ext.filters import (
    FilterDataDict,
    MessageFilter,
)


class SlashFilter(MessageFilter):
    """
    Filter messages starting with a slash or backslash.
    """

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
    """
    Filter messages with text length not in range [min_length, max_length].
    """

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
    """
    Filter messages that mention the bot.
    """

    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.text:
            return False
        if f"@{message.get_bot().username}" not in message.text:
            return False
        return True


class ReplyBotFilter(MessageFilter):
    """
    Filter messages that reply to the bot.
    """

    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if not message.reply_to_message:
            return False
        if (
            not message.reply_to_message.from_user.username
            == message.get_bot().username
        ):
            return False
        return True


_service_message_attr = [
    "delete_chat_photo",
    "message_auto_delete_timer_changed",
    "video_chat_scheduled",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_participants_invited",
    "new_chat_photo",
    "pinned_message",
    "new_chat_members",
    "left_chat_member",
    "new_chat_title",
]


class ServiceMessageFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if any(getattr(message, attr) for attr in _service_message_attr):
            return True
        return False


class AutoForwardFilter(MessageFilter):
    def filter(self, message: Message) -> bool | FilterDataDict | None:
        if message.chat.type not in [message.chat.GROUP, message.chat.SUPERGROUP]:
            return False
        if message.is_automatic_forward:
            return True
        return False


mention_or_private_filter = MentionBotFilter() | filters.ChatType.PRIVATE
slash_filter = SlashFilter() & TextLengthFilter(min_length=1, max_length=100)
reply_filter = (TextLengthFilter(min_length=1, max_length=200) & ~slash_filter) & (
    ReplyBotFilter() | MentionBotFilter() | filters.ChatType.PRIVATE
)
service_message_filter = ServiceMessageFilter()
auto_forward_filter = AutoForwardFilter()
mention_bot_filter = MentionBotFilter()
