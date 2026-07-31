"""The `/rss` command: subscribe a chat to RSS/Atom feeds.

Subcommands mirror the panel's subscription page: `sub <url>`, `list`, and
`unsub`/`pause`/`resume` addressed by the 1-based index shown in `list` — a phone
user should not have to retype a long URL to unpause a feed. `add`/`remove` are
accepted as aliases for the newer `sub`/`unsub` spellings.

The whitelist gate (`rss_allowed` policy flag) applies to every subcommand,
including `list`: an un-whitelisted chat should not even see the feature.
"""

import html

import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua import database, i18n
from kmua.common.tgmethod import can_user_manage_bot_in_chat
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.panel import chat_panel_button, panel_available
from kmua.services import rss as rss_service
from kmua.services.rss import redact_url
from kmua.webapp.errors import ApiError
from kmua.webapp.ratelimit import SlidingWindowLimiter

_T = pyrogram.types

# Telegram's /rss add path has no write_limiter (that guards the HTTP API), so
# the outbound validation fetch is throttled here per chat+user.
_rss_add_limiter = SlidingWindowLimiter(limit=10, window=60.0)


def _panel_markup(chat: _T.Chat, lang: str) -> _T.InlineKeyboardMarkup | None:
    """A button into the panel for this chat, or None when the panel is not
    configured. Groups get the `?startapp=` deep link (a Mini App button only
    works in private chats); private chats get a real web-app button.
    """
    if not panel_available():
        return None
    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        button = _T.InlineKeyboardButton(
            i18n.t("bot.msg.rss.open_panel", locale=lang),
            web_app=_T.WebAppInfo(url=f"{app_config.webapp_url}/me/rss"),
        )
    else:
        chat_id = chat.id
        if chat_id is None:
            return None
        button = chat_panel_button(chat_id, lang)
        if button is None:
            return None
    return _T.InlineKeyboardMarkup([[button]])


@PyrogramClient.on_message(pyrogram.filters.command("rss"), group=0)
async def rss_command(client: PyrogramClient, message: _T.Message):
    if not app_config.rss_enabled:
        await message.reply(i18n.t("bot.msg.rss.disabled", locale=app_config.lang))
        return

    chat = message.chat
    user = message.from_user or message.sender_chat
    if not user or not user.id or not chat or not chat.id:
        return

    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user.id)).lang
    else:
        chat_config = await database.get_chat_config(chat.id)
        lang = chat_config.lang
        # `can_user_manage_bot_in_chat` raises on private chats, so this branch
        # must come after the private-chat check above.
        if not await can_user_manage_bot_in_chat(user, chat):
            await message.reply(i18n.t("bot.msg.no_permission_group", locale=lang))
            return

    if not await database.is_rss_allowed(chat.id):
        await message.reply(
            i18n.t("bot.msg.rss.not_allowed", locale=lang).format(chat_id=chat.id)
        )
        return

    command = message.command or []
    if len(command) < 2:
        await message.reply(
            i18n.t("bot.msg.rss.usage", locale=lang),
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=_panel_markup(chat, lang),
        )
        return

    action = command[1].lower()
    match action:
        case "sub" | "add":
            await _rss_add(message, chat, chat.id, user.id, lang, command)
        case "list":
            await _rss_list(message, chat, chat.id, lang)
        case "unsub" | "remove" | "pause" | "resume":
            await _rss_manage(message, chat.id, action, lang, command)
        case "interval":
            await _rss_interval(message, chat.id, lang, command)
        case "testpush":
            await _rss_testpush(client, message, chat.id, user.id, lang, command)
        case _:
            await message.reply(
                i18n.t("bot.msg.rss.usage", locale=lang),
                parse_mode=pyrogram.enums.ParseMode.HTML,
                reply_markup=_panel_markup(chat, lang),
            )


async def _rss_add(
    message: _T.Message,
    chat: _T.Chat,
    chat_id: int,
    user_id: int,
    lang: str,
    command: list[str],
) -> None:
    url = " ".join(command[2:]).strip()
    if not url.startswith(("http://", "https://")) or len(url) > 1024:
        await message.reply(i18n.t("bot.msg.rss.invalid_url", locale=lang))
        return

    # The per-chat cap is enforced before any outbound fetch: a chat already at
    # its cap must not be able to turn `/rss add` into an open fetcher.
    if await database.count_chat_subscriptions(chat_id) >= database.MAX_FEEDS_PER_CHAT:
        await message.reply(
            i18n.t("bot.msg.rss.limit_reached", locale=lang).format(
                limit=database.MAX_FEEDS_PER_CHAT
            )
        )
        return

    try:
        _rss_add_limiter.check(f"{chat_id}:{user_id}")
    except ApiError as e:
        await message.reply(
            i18n.t("bot.msg.rss.too_many_requests", locale=lang).format(error=e.message)
        )
        return

    # Validate synchronously before subscribing: a URL that cannot be fetched
    # today would otherwise be a silent never-pushing subscription.
    try:
        result = await rss_service.fetch_feed(url)
    except Exception as e:
        await message.reply(
            i18n.t("bot.msg.rss.fetch_failed", locale=lang).format(
                error=e.__class__.__name__
            )
        )
        logger.error(f"rss: add validation fetch failed for {redact_url(url)}: {e}")
        return

    sub, reason = await database.add_subscription(chat_id, url, created_by=user_id)
    if sub is None:
        if reason == "already_subscribed":
            await message.reply(i18n.t("bot.msg.rss.already_subscribed", locale=lang))
        else:
            await message.reply(
                i18n.t("bot.msg.rss.limit_reached", locale=lang).format(
                    limit=database.MAX_FEEDS_PER_CHAT
                )
            )
        return

    # Seed the seen window right away, matching the poll job's first-fetch rule:
    # a fresh subscription must not be flooded with the feed's history on the
    # next poll.
    await database.record_fetch_success(
        sub.feed_id,
        title=result.feed_title,
        etag=result.etag,
        last_modified=result.last_modified,
        seen_entry_ids=[e.entry_id for e in result.entries],
    )

    feed_title = result.feed_title or url
    await message.reply(
        i18n.t("bot.msg.rss.added", locale=lang).format(title=feed_title),
        reply_markup=_panel_markup(chat, lang),
    )


async def _rss_list(
    message: _T.Message, chat: _T.Chat, chat_id: int, lang: str
) -> None:
    subs = await database.get_chat_subscriptions(chat_id)
    if not subs:
        await message.reply(
            i18n.t("bot.msg.rss.empty", locale=lang),
            reply_markup=_panel_markup(chat, lang),
        )
        return

    lines = []
    for idx, sub in enumerate(subs, 1):
        title = sub.feed.title or sub.feed.url
        url = html.escape(sub.feed.url)
        interval = sub.interval_minutes or app_config.rss_interval
        line = f'{idx}. <a href="{url}">{html.escape(title)}</a>' + i18n.t(
            "bot.msg.rss.interval_mark", locale=lang
        ).format(minutes=interval)
        if sub.paused:
            line += i18n.t("bot.msg.rss.paused_mark", locale=lang)
        if sub.feed.last_error:
            line += i18n.t("bot.msg.rss.error_mark", locale=lang)
        lines.append(line)
    await message.reply(
        "\n".join(lines),
        parse_mode=pyrogram.enums.ParseMode.HTML,
        reply_markup=_panel_markup(chat, lang),
    )


async def _rss_manage(
    message: _T.Message, chat_id: int, action: str, lang: str, command: list[str]
) -> None:
    subs = await database.get_chat_subscriptions(chat_id)
    try:
        index = int(command[2]) - 1
        sub = subs[index]
    except (ValueError, IndexError):
        await message.reply(i18n.t("bot.msg.rss.invalid_index", locale=lang))
        return

    feed_id = sub.feed_id
    feed_title = sub.feed.title or sub.feed.url
    match action:
        case "unsub" | "remove":
            await database.remove_subscription(chat_id, feed_id)
            await message.reply(
                i18n.t("bot.msg.rss.removed", locale=lang).format(title=feed_title)
            )
        case "pause":
            await database.set_subscription_paused(chat_id, feed_id, True)
            await message.reply(
                i18n.t("bot.msg.rss.paused", locale=lang).format(title=feed_title)
            )
        case "resume":
            await database.set_subscription_paused(chat_id, feed_id, False)
            await message.reply(
                i18n.t("bot.msg.rss.resumed", locale=lang).format(title=feed_title)
            )


async def _rss_interval(
    message: _T.Message, chat_id: int, lang: str, command: list[str]
) -> None:
    """Set one subscription's poll interval; no minute argument = global default."""
    subs = await database.get_chat_subscriptions(chat_id)
    try:
        index = int(command[2]) - 1
        sub = subs[index]
    except (ValueError, IndexError):
        await message.reply(i18n.t("bot.msg.rss.invalid_index", locale=lang))
        return

    if len(command) < 4:
        minutes = None
    else:
        try:
            minutes = int(command[3])
        except ValueError:
            minutes = -1
        if not (
            database.MIN_SUBSCRIPTION_INTERVAL
            <= minutes
            <= database.MAX_SUBSCRIPTION_INTERVAL
        ):
            await message.reply(
                i18n.t("bot.msg.rss.interval_invalid", locale=lang).format(
                    min=database.MIN_SUBSCRIPTION_INTERVAL,
                    max=database.MAX_SUBSCRIPTION_INTERVAL,
                )
            )
            return

    await database.set_subscription_interval(chat_id, sub.feed_id, minutes)
    if minutes is None:
        await message.reply(i18n.t("bot.msg.rss.interval_reset", locale=lang))
    else:
        await message.reply(
            i18n.t("bot.msg.rss.interval_set", locale=lang).format(minutes=minutes)
        )


async def _rss_testpush(
    client: PyrogramClient,
    message: _T.Message,
    chat_id: int,
    user_id: int,
    lang: str,
    command: list[str],
) -> None:
    """Fetch one subscribed feed now and push its latest entries to this chat.

    A manual "push now" for testing: unlike the poll job it ignores the seen
    window (a feed with no new entries must still produce visible output), but
    the pushed entries are marked seen so the next poll does not duplicate them.
    """
    subs = await database.get_chat_subscriptions(chat_id)
    try:
        index = int(command[2]) - 1
        sub = subs[index]
    except (ValueError, IndexError):
        await message.reply(i18n.t("bot.msg.rss.invalid_index", locale=lang))
        return

    try:
        _rss_add_limiter.check(f"{chat_id}:{user_id}")
    except ApiError as e:
        await message.reply(
            i18n.t("bot.msg.rss.too_many_requests", locale=lang).format(error=e.message)
        )
        return

    try:
        result = await rss_service.fetch_feed(
            sub.feed.url, etag=sub.feed.etag, last_modified=sub.feed.last_modified
        )
    except Exception as e:
        await message.reply(
            i18n.t("bot.msg.rss.fetch_failed", locale=lang).format(
                error=e.__class__.__name__
            )
        )
        logger.error(f"rss: testpush fetch failed for {redact_url(sub.feed.url)}: {e}")
        return

    pushed = 0
    for entry in result.entries[: rss_service.MAX_ENTRIES_PER_PUSH]:
        text = rss_service.render_entry(result.feed_title or sub.feed.url, entry, lang)
        try:
            if entry.media_urls:
                await client.send_photo(
                    chat_id,
                    photo=entry.media_urls[0],
                    caption=rss_service.truncate_for_delivery(text, 1024),
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
            else:
                await client.send_message(
                    chat_id,
                    rss_service.truncate_for_delivery(text, 4096),
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                    disable_web_page_preview=False,
                )
            pushed += 1
        except Exception as e:
            logger.error(f"rss: testpush send to {chat_id} failed: {e}")
            break

    await database.record_fetch_success(
        sub.feed_id,
        title=result.feed_title,
        etag=result.etag,
        last_modified=result.last_modified,
        seen_entry_ids=[e.entry_id for e in result.entries],
    )
    await message.reply(
        i18n.t("bot.msg.rss.testpush_done", locale=lang).format(count=pushed)
    )
