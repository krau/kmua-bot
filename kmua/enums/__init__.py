from enum import IntEnum, StrEnum


# https://python-telegram-bot.org/
class ChatID(IntEnum):
    """This enum contains some special chat IDs. The enum
    members of this enumeration are instances of :class:`int` and can be treated as such.

    """

    __slots__ = ()

    ANONYMOUS_ADMIN = 1087968824
    """:obj:`int`: User ID in groups for messages sent by anonymous admins. Telegram chat:
    `@GroupAnonymousBot <https://t.me/GroupAnonymousBot>`_.

    Note:
        :attr:`telegram.Message.from_user` will contain this ID for backwards compatibility only.
        It's recommended to use :attr:`telegram.Message.sender_chat` instead.
    """
    SERVICE_CHAT = 777000
    """:obj:`int`: Telegram service chat, that also acts as sender of channel posts forwarded to
    discussion groups. Telegram chat: `Telegram <https://t.me/+42777>`_.

    Note:
        :attr:`telegram.Message.from_user` will contain this ID for backwards compatibility only.
        It's recommended to use :attr:`telegram.Message.sender_chat` instead.
    """
    FAKE_CHANNEL = 136817688
    """:obj:`int`: User ID in groups when message is sent on behalf of a channel, or when a channel
    votes on a poll. Telegram chat: `@Channel_Bot <https://t.me/Channel_Bot>`_.
    """


class GLockKey(StrEnum):
    """This enum contains keys for the global lock."""

    __slots__ = ()

    CLEANING = "cleaning"


class VerifyTrigger(StrEnum):
    """新成员验证触发策略(何时验证), 与验证方式解耦。现仅实现 all, 枚举保留扩展位。"""

    __slots__ = ()

    ALL = "all"


class VerifyMethod(StrEnum):
    """新成员验证方式(如何验证), 与触发策略解耦。"""

    __slots__ = ()

    MATH = "math"
    EMOJI = "emoji"
    STICKER = "sticker"
    CUSTOM_QA = "custom_qa"


class VerifyFailAction(StrEnum):
    """验证失败(超时/次数耗尽)后对用户采取的动作。"""

    __slots__ = ()

    KICK = "kick"  # ban+unban, 移出但不拉黑, 可重新加群再验证
    BAN = "ban"  # 永久拉黑
    UNRESTRICT = "unrestrict"  # 仅解除限制, 留在群里
