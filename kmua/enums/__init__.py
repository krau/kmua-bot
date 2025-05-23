from enum import IntEnum


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
