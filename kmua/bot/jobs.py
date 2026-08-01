import asyncio
import html
import io
import random
from datetime import UTC, datetime, timedelta

import httpx
import pyrogram
import pyrogram.errors

from kmua import common, database, enums, i18n
from kmua.config import app_config
from kmua.database.models import ChatConfig
from kmua.logger import logger


async def cleanup():
    try:
        logger.info("cleaning data")
        await common.memstore.set(enums.GLockKey.CLEANING, True)
        await database.cleanup_waifu_data()
        # await database.cleanup_user_avatar()
        # common.cleanup_avatar_cache()
    finally:
        logger.info("clean data done")
        await common.memstore.delete(enums.GLockKey.CLEANING)


async def change_bot_avatar():
    """
    定时更换 bot 头像
    使用 manyacg 获取随机图片，aniobjcut 裁切为头像，然后更新 bot profile photo
    """
    from kmua.bot.client import client
    from kmua.services import aniobjcut, manyacg

    if not manyacg.manyacg_client or not aniobjcut.aniobjcut_client:
        logger.warning(i18n.t("log.avatar_change_disabled", locale=app_config.lang))
        return

    try:
        logger.info(i18n.t("log.avatar_changing", locale=app_config.lang))

        # 获取随机图片
        resp = await manyacg.manyacg_client.random_artwork(limit=1, r18=0)
        if resp.status != 200 or not resp.data:
            logger.error(f"failed to get random artwork: {resp.message}")
            return

        artwork = resp.data[0]
        picture = artwork.pictures[random.randint(0, len(artwork.pictures) - 1)]

        # 下载图片
        async with httpx.AsyncClient(timeout=30) as http_client:
            fileresp = await http_client.get(
                f"{app_config.manyacg_api_url}/picture/file/{picture.id}",
            )
            fileresp.raise_for_status()

        # 裁切为头像
        avatar = await aniobjcut.aniobjcut_client.cut_avatar(fileresp.content)

        await client.set_profile_photo(
            pyrogram.types.InputChatPhotoStatic(io.BytesIO(avatar))
        )
        logger.success(
            i18n.t("log.avatar_changed", locale=app_config.lang).format(
                title=artwork.title, url=artwork.source_url
            )
        )

    except Exception as e:
        logger.exception(
            i18n.t("log.avatar_change_failed", locale=app_config.lang).format(
                error=str(e)
            )
        )


async def rss_push():
    """Poll every active feed whose cadence is due, and deliver new entries.

    Runs every minute (see the `__main__` registration) but only fetches feeds
    whose effective interval has elapsed: the effective interval of a feed is the
    minimum across its unpaused subscriptions, falling back to
    `app_config.rss_interval` for subscriptions without their own. Feeds are
    polled sequentially rather than concurrently: this runs on the bot's only
    event loop, and a burst of parallel fetches competes with message handling
    for it.
    """
    if not app_config.rss_enabled:
        return

    from kmua.services import rss as rss_service
    from kmua.services.rss import redact_url

    feeds = await database.get_active_feeds()
    if not feeds:
        return

    now = datetime.now(UTC)
    pushed = 0
    fetched = 0
    for feed, interval_minutes in feeds:
        if feed.failure_count >= rss_service.MAX_FAILURES:
            logger.warning(
                f"rss: skipping feed {feed.id} ({feed.url}) after "
                f"{feed.failure_count} consecutive failures"
            )
            continue

        if feed.last_fetched_at is not None:
            last = feed.last_fetched_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last < timedelta(minutes=interval_minutes):
                continue
        fetched += 1

        try:
            result = await rss_service.fetch_feed(
                feed.url, etag=feed.etag, last_modified=feed.last_modified
            )
        except Exception as e:
            error = f"{e.__class__.__name__}: {e}"
            # The exception string embeds the full request URL; a signed feed
            # URL must not reach the logs or the `last_error` column.
            error = error.replace(feed.url, redact_url(feed.url))
            logger.error(f"rss: fetch failed for {redact_url(feed.url)}: {error}")
            await database.record_fetch_failure(feed.id, error)
            continue

        if result.not_modified:
            # A 304 is still a fetch: bump the timestamp so the next tick does
            # not immediately re-request.
            await database.touch_fetch(feed.id)
            continue

        if feed.last_fetched_at is None:
            # First fetch: seed the seen window without pushing anything, so a fresh
            # subscription is not flooded with the feed's entire history.
            await database.record_fetch_success(
                feed.id,
                title=result.feed_title,
                etag=result.etag,
                last_modified=result.last_modified,
                seen_entry_ids=[e.entry_id for e in result.entries],
            )
            continue

        seen = set(feed.seen_entry_ids or [])
        new_entries = [e for e in result.entries if e.entry_id not in seen][
            : rss_service.MAX_ENTRIES_PER_PUSH
        ]

        # The seen window slides regardless of whether anything is new, so an entry
        # that fell out of the window cannot be re-pushed on the next poll.
        await database.record_fetch_success(
            feed.id,
            title=result.feed_title,
            etag=result.etag,
            last_modified=result.last_modified,
            seen_entry_ids=[e.entry_id for e in result.entries] + list(seen),
        )

        if not new_entries:
            continue

        chat_ids = await database.get_feed_target_chats(feed.id)
        lang_by_chat: dict[int, str] = {}
        for chat_id in chat_ids:
            if chat_id not in lang_by_chat:
                lang_by_chat[chat_id] = await _chat_lang(chat_id)

        # Per-chat agent switches: summary digests are generated once per
        # language (a feed usually fans out to several chats), broadcasts once
        # per broadcast-enabled group chat.
        chat_configs: dict[int, ChatConfig] = {}
        summary_langs: set[str] = set()
        broadcast_chats: list[tuple[int, str]] = []
        for chat_id in chat_ids:
            try:
                chat_configs[chat_id] = await database.get_chat_config(chat_id)
            except ValueError:
                continue  # chat row missing; _deliver_entry decides cleanup
            if chat_configs[chat_id].rss_agent_summary:
                summary_langs.add(lang_by_chat[chat_id])
            if chat_configs[chat_id].rss_agent_broadcast:
                broadcast_chats.append((chat_id, lang_by_chat[chat_id]))

        digest_by_lang: dict[str, dict[str, str]] = {}
        broadcast_by_lang: dict[str, str | None] = {}
        broadcast_targets: dict[
            int, str
        ] = {}  # chat_id -> lang (group, not rate-limited)
        if app_config.agent and app_config.agent_model:
            from kmua.plugins.agent.rss_digest import (
                generate_rss_broadcast,
                generate_rss_digest,
            )

            # Never leak a signed feed URL into logs or the model prompt when
            # the feed has no title (same redaction the fetch path uses).
            feed_label = result.feed_title or redact_url(feed.url)
            for lang in summary_langs:
                digest_by_lang[lang] = await generate_rss_digest(
                    new_entries, feed_label, lang
                )
            # Skip broadcasts while the per-chat rate-limit lock is held:
            # generating first would burn get_chat + LLM calls every poll.
            for chat_id, lang in broadcast_chats:
                if await _broadcast_locked(chat_id):
                    continue
                if not await _is_group_chat(chat_id):
                    continue
                broadcast_targets[chat_id] = lang
            for lang in set(broadcast_targets.values()):
                broadcast_by_lang[lang] = await generate_rss_broadcast(
                    new_entries, feed_label, lang
                )

        for chat_id in chat_ids:
            for entry in new_entries:
                text = rss_service.render_entry(
                    result.feed_title or feed.url, entry, lang_by_chat[chat_id]
                )
                chat_config = chat_configs.get(chat_id)
                if chat_config and chat_config.rss_agent_summary:
                    digest = digest_by_lang.get(lang_by_chat[chat_id], {}).get(
                        entry.entry_id
                    )
                    if digest:
                        text = f"💬 {html.escape(digest)}\n\n{text}"
                if await _deliver_entry(chat_id, text, entry.media_urls):
                    pushed += 1
                await asyncio.sleep(0.5)
            if chat_id in broadcast_targets:
                text = broadcast_by_lang.get(broadcast_targets[chat_id])
                if text is not None:
                    await _try_broadcast(chat_id, text)

    logger.info(
        f"rss: {len(feeds)} active feed(s), fetched {fetched}, "
        f"pushed {pushed} message(s)"
    )


async def _chat_lang(chat_id: int) -> str:
    """Resolve the delivery language for one chat.

    Groups and channels store it in their chat config. A private chat is a user,
    not a chat, so it has no chat_data row - fall back to the user config, and to
    the bot-wide language when even that is unavailable. A missing row must never
    abort the poll or drop the subscription: `_deliver_entry` decides whether the
    chat is reachable, and permanent delivery failures are the only cleanup path.
    """
    try:
        return (await database.get_chat_config(chat_id)).lang
    except ValueError:
        pass
    if chat_id < 0:
        return app_config.lang
    try:
        return (await database.get_user_config(chat_id)).lang
    except Exception:
        return app_config.lang


async def _deliver_entry(chat_id: int, text: str, media_urls: list[str]) -> bool:
    """Send one rendered entry. False when the chat is gone and was cleaned up.

    With media, the text becomes the photo's caption (Telegram's 1024-char limit
    applies); without it the entry is a plain text message. Either way the text
    is shrunk to fit without breaking its HTML.
    """
    from kmua.bot.client import client
    from kmua.services import rss as rss_service

    async def send() -> None:
        if media_urls:
            await client.send_photo(
                chat_id,
                photo=media_urls[0],
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

    try:
        await send()
        return True
    except pyrogram.errors.FloodWait as e:
        logger.warning(f"rss: flood wait {e.value}s for chat {chat_id}")
        # pyrogram annotates `FloodWait.value` loosely (int | str | RpcError); it
        # is an int at runtime, and getattr sidesteps the annotation.
        await asyncio.sleep(int(getattr(e, "value", 1)) + 1)
        try:
            await send()
            return True
        except Exception as retry_error:
            logger.error(
                f"rss: retry after flood failed for chat {chat_id}: {retry_error}"
            )
            return False
    except (
        pyrogram.errors.ChatWriteForbidden,
        pyrogram.errors.ChannelPrivate,
        pyrogram.errors.UserIsBlocked,
        pyrogram.errors.PeerIdInvalid,
    ):
        # The chat is unreachable for good; keeping its subscriptions would make
        # every future poll fail the same way. This is the only path that removes
        # subscriptions automatically.
        await database.delete_chat_subscriptions(chat_id)
        logger.info(f"rss: chat {chat_id} unreachable, subscriptions cleaned up")
        return False
    except Exception as e:
        logger.error(
            f"rss: deliver to chat {chat_id} failed: {e.__class__.__name__}: {e}"
        )
        return False


async def _is_group_chat(chat_id: int) -> bool:
    """True when the chat is a supergroup or group (broadcast target only)."""
    from kmua.bot.client import client

    try:
        chat = await client.get_chat(chat_id)
    except Exception as e:
        logger.warning(
            f"rss: broadcast chat lookup failed for {chat_id}: "
            f"{e.__class__.__name__}: {e}"
        )
        return False
    return chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )


async def _broadcast_locked(chat_id: int) -> bool:
    """True while the per-chat broadcast rate-limit lock is held.

    Read-only peek used before generation so rate-limited chats do not burn
    LLM calls; the lock itself is only acquired at send time.
    """
    return bool(await common.memttlcache.get(f"rss:broadcast:{chat_id}"))


async def _broadcast_due(chat_id: int) -> bool:
    """Rate-limit gate: one broadcast per chat per configured interval.

    Locks via memttlcache; a bot restart resets the lock, which is acceptable
    (broadcasts are best-effort chatter, not a delivery guarantee).
    """
    key = f"rss:broadcast:{chat_id}"
    if await common.memttlcache.get(key):
        return False
    await common.memttlcache.set(
        key, True, ttl=app_config.rss_agent_broadcast_interval * 60
    )
    return True


async def _try_broadcast(chat_id: int, text: str | None) -> None:
    """Send one agent-written broadcast message, rate-limited per chat.

    Sent as plain text (parse_mode=None): the model output is untrusted and
    must not be interpreted as HTML. Failures are logged and swallowed; a
    broadcast never cleans up subscriptions or affects the regular push.
    """
    if not text or not await _broadcast_due(chat_id):
        return
    from kmua.bot.client import client

    try:
        await client.send_message(chat_id, text, parse_mode=None)
        logger.debug(f"rss: broadcast sent to {chat_id}")
    except Exception as e:
        logger.warning(
            f"rss: broadcast to chat {chat_id} failed: {e.__class__.__name__}: {e}"
        )
