"""Entry points into the Mini App panel.

The panel is a Mini App, and Telegram will only hand a `web_app` button its launch
parameters in a private chat. In a group the equivalent is a plain URL button on the
`t.me/<bot>/<app>?startapp=` form, which opens the same app and carries a parameter
saying which chat it came from.

So a group gets a link, a private chat gets a real Mini App button, and both land on
the same panel. The `startapp` value is only a navigation hint - the panel re-checks
permissions server-side before reading or writing anything.
"""

import pyrogram
from pyrogram.client import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from kmua import common, database
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.webapp.auth import build_chat_start_param


def panel_available() -> bool:
    """Whether a panel link can be built at all.

    A deep link needs the bot's username and the app's short name in addition to the
    panel being enabled, so all four are checked together rather than at each call
    site.
    """
    from kmua.bot.client import client

    if not (app_config.webapp and app_config.webapp_url):
        return False
    bot_username = client.me.username if client.me else None
    return bool(bot_username and app_config.webapp_short_name)


def chat_panel_url(chat_id: int) -> str | None:
    """A deep link to `chat_id`'s page in the panel, or None if unavailable."""
    from kmua.bot.client import client

    if not panel_available():
        return None
    bot_username = client.me.username if client.me else None
    start_param = build_chat_start_param(chat_id)
    return (
        f"https://t.me/{bot_username}/"
        f"{app_config.webapp_short_name}?startapp={start_param}"
    )


def chat_panel_button(chat_id: int, lang: str) -> InlineKeyboardButton | None:
    """The "configure in the panel" button for a group, or None if unavailable."""
    url = chat_panel_url(chat_id)
    if url is None:
        return None
    return InlineKeyboardButton(
        i18n.t("bot.button.chat_panel", locale=lang),
        url=url,
    )


@Client.on_message(pyrogram.filters.command("panel") & pyrogram.filters.group, group=0)
async def panel_group_cmd(client: Client, message: pyrogram.types.Message):
    """Open this group's page in the panel.

    Same permission check as /config, since it leads to the same settings. The reply
    carries the link rather than opening anything directly: a bot cannot open a Mini
    App on the user's behalf.
    """
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not chat or chat.id is None or not user:
        return
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang

    if not await common.can_user_manage_bot_in_chat(user, chat):
        await message.reply(text=i18n.t("bot.msg.no_permission_group", locale=lang))
        return

    button = chat_panel_button(chat.id, lang)
    if button is None:
        await message.reply(text=i18n.t("bot.msg.panel_unavailable", locale=lang))
        return

    await message.reply(
        text=i18n.t("bot.msg.chat_panel", locale=lang),
        reply_markup=InlineKeyboardMarkup([[button]]),
    )
