"""Endpoints for a user's own profile and content.

Everything here is scoped to the caller by construction: the user id comes from
the session, never from the request, so there is no per-row ownership check to
forget.
"""

from __future__ import annotations

import html
import random

from fastapi import APIRouter, Path, Query, Request
from pyrogram.enums import ParseMode

from kmua import common, database
from kmua.bot.client import client
from kmua.common import ops
from kmua.config import app_config
from kmua.gift import define as gift_define
from kmua.gift.service import send_gift_to_bot
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.services import rss as rss_service
from kmua.services.rss import redact_url
from kmua.webapp import audit
from kmua.webapp.deps import CurrentUser, client_key
from kmua.webapp.errors import ApiError, ErrorCode, forbidden, not_found
from kmua.webapp.ratelimit import write_limiter
from kmua.webapp.schemas import (
    ChatBriefOut,
    GiftCatalogOut,
    GiftOut,
    GiftPurchaseIn,
    GiftUseOut,
    MeConfigPatch,
    MeOut,
    PageOut,
    QuoteOut,
    RssSubscriptionIn,
    RssSubscriptionOut,
    RssSubscriptionPatch,
    WaifuEntryOut,
    WaifuOut,
)
from kmua.webapp.serializers import quote_out, rss_subscription_out, timestamp

router = APIRouter(prefix="/api/me", tags=["me"])


def gift_out(gift_entry) -> GiftOut:
    try:
        gift_id = gift_define.GiftID(gift_entry.gift_id)
        display = gift_define.get_display_name(gift_id)
    except ValueError:
        display = gift_entry.gift_id
    return GiftOut(
        id=gift_entry.id,
        gift_id=gift_entry.gift_id,
        display_name=display,
        rarity=gift_entry.rarity,
        rarity_name=gift_define.get_rarity_display_name(gift_entry.rarity),
        sent_to_bot=gift_entry.sent_to_bot,
        created_at=timestamp(gift_entry.created_at),
    )


@router.get("", response_model=MeOut)
async def read_me(user: CurrentUser) -> MeOut:
    config = user.data.user_config
    married_name: str | None = None
    if user.data.married_waifu_id:
        partner = await database.get_user_by_id(user.data.married_waifu_id)
        married_name = partner.full_name if partner else None

    percentile: float | None
    try:
        percentile = await database.get_affection_percentile(config.affection)
    except Exception as e:
        # The histogram is an optimisation; a stale one must not break the page.
        logger.warning(f"webapp: affection percentile failed for {user.id}: {e}")
        percentile = None

    chats = await database.get_user_chats(user.id)

    return MeOut(
        id=user.id,
        full_name=user.data.full_name,
        username=user.data.username,
        lang=config.lang,
        coins=config.coins,
        affection=config.affection,
        affection_percentile=percentile,
        waifu_mention=user.data.waifu_mention,
        is_married=user.data.is_married,
        married_waifu_id=user.data.married_waifu_id,
        married_waifu_name=married_name,
        quote_count=await database.get_user_quote_count(user.id),
        gift_count=await database.count_user_gifts(user.id),
        chat_count=len(chats),
        roles=user.roles,
    )


@router.patch("/config", response_model=MeOut)
async def update_my_config(
    request: Request, user: CurrentUser, payload: MeConfigPatch
) -> MeOut:
    """Apply the fields present in the payload; absent fields stay untouched."""
    write_limiter.check(client_key(request, user.id))

    if payload.lang is not None:
        config = user.data.user_config
        config.lang = payload.lang
        await database.update_user_config(user.id, config)

    if payload.waifu_mention is not None:
        await database.set_user_waifu_mention(user.id, payload.waifu_mention)

    refreshed = await database.get_user_by_id(user.id)
    if refreshed is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "User disappeared")
    user.data = refreshed
    return await read_me(user)


@router.get("/chats", response_model=list[ChatBriefOut])
async def list_my_chats(user: CurrentUser) -> list[ChatBriefOut]:
    """Groups shared with the bot, flagged with whether the caller can manage them.

    Owners and global admins can manage everything. For everyone else this reports
    the stored bot-admin flag; the authoritative check happens when they actually
    open a chat, so a group owner who has never used /botpromote is not locked out.
    """
    rows = await database.get_user_chats(user.id)
    return [
        ChatBriefOut(
            id=chat.id,
            title=chat.title,
            username=chat.username,
            can_manage=user.is_admin or is_bot_admin,
        )
        for chat, is_bot_admin in rows
    ]


@router.get("/quotes", response_model=PageOut[QuoteOut])
async def list_my_quotes(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> PageOut[QuoteOut]:
    result = await database.get_user_quotes_paged(user.id, page=page, size=size)
    return PageOut[QuoteOut](
        items=[quote_out(quote) for quote in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
    )


@router.delete("/quotes/{link:path}", status_code=204)
async def delete_my_quote(
    request: Request,
    user: CurrentUser,
    link: str = Path(description="Full message link identifying the quote"),
) -> None:
    """Delete one of the caller's own quotes.

    Ownership is verified before deleting: the link is a client-supplied key, so
    without this check any user could delete anyone's quote.
    """
    write_limiter.check(client_key(request, user.id))

    quote = await database.get_quote_by_link(link)
    if quote is None:
        raise not_found(ErrorCode.QUOTE_NOT_FOUND, "Quote not found")
    if quote.user_id != user.id:
        raise not_found(ErrorCode.QUOTE_NOT_FOUND, "Quote not found")
    await database.delete_quote(link)


# ------------------------------------------------------------------ rss

# A user's private chat with the bot IS the user's id, so the personal RSS
# endpoints are the group endpoints applied to `user.id` as the chat. The gates
# are identical (feature switch + whitelist policy); the subscription CRUD is
# shared.


@router.get("/rss", response_model=PageOut[RssSubscriptionOut])
async def list_my_rss(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> PageOut[RssSubscriptionOut]:
    if not app_config.rss_enabled:
        raise ApiError(ErrorCode.FEATURE_DISABLED, "RSS is disabled")
    if not await database.is_rss_allowed(user.id):
        raise forbidden(ErrorCode.FORBIDDEN, "RSS is not enabled for this chat")

    result = await database.get_chat_subscriptions_paged(user.id, page=page, size=size)
    return PageOut[RssSubscriptionOut](
        items=[rss_subscription_out(sub) for sub in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
    )


@router.post("/rss", response_model=RssSubscriptionOut, status_code=201)
async def add_my_rss(
    request: Request, user: CurrentUser, payload: RssSubscriptionIn
) -> RssSubscriptionOut:
    if not app_config.rss_enabled:
        raise ApiError(ErrorCode.FEATURE_DISABLED, "RSS is disabled")
    if not await database.is_rss_allowed(user.id):
        raise forbidden(ErrorCode.FORBIDDEN, "RSS is not enabled for this chat")
    write_limiter.check(client_key(request, user.id))

    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "URL must be http(s)")

    try:
        result = await rss_service.fetch_feed(url)
    except Exception as e:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, f"Feed unreachable: {e.__class__.__name__}"
        )

    sub, reason = await database.add_subscription(user.id, url, created_by=user.id)
    if sub is None:
        if reason == "already_subscribed":
            raise ApiError(ErrorCode.CONFLICT, "Already subscribed", 409)
        raise ApiError(ErrorCode.CONFLICT, "Subscription limit reached", 409)

    await database.record_fetch_success(
        sub.feed_id,
        title=result.feed_title,
        etag=result.etag,
        last_modified=result.last_modified,
        seen_entry_ids=[e.entry_id for e in result.entries],
    )

    fresh = next(
        s
        for s in await database.get_chat_subscriptions(user.id)
        if s.feed_id == sub.feed_id
    )

    audit.record(
        action="me.rss.add",
        actor_id=user.id,
        actor_roles=user.roles,
        target=f"{user.id}",
        extra={"url": redact_url(url)},
    )
    return rss_subscription_out(fresh)


@router.patch("/rss/{feed_id}", response_model=list[RssSubscriptionOut])
async def update_my_rss(
    request: Request,
    user: CurrentUser,
    payload: RssSubscriptionPatch,
    feed_id: int = Path(description="Feed the subscription points at"),
) -> list[RssSubscriptionOut]:
    if not app_config.rss_enabled:
        raise ApiError(ErrorCode.FEATURE_DISABLED, "RSS is disabled")
    if not await database.is_rss_allowed(user.id):
        raise forbidden(ErrorCode.FORBIDDEN, "RSS is not enabled for this chat")
    write_limiter.check(client_key(request, user.id))

    fields = payload.model_fields_set
    updated = False
    if "paused" in fields and payload.paused is not None:
        updated = (
            await database.set_subscription_paused(user.id, feed_id, payload.paused)
            or updated
        )
    if "interval_minutes" in fields:
        updated = (
            await database.set_subscription_interval(
                user.id, feed_id, payload.interval_minutes
            )
            or updated
        )
    if not updated:
        raise not_found(ErrorCode.NOT_FOUND, "Subscription not found")

    audit.record(
        action="me.rss.update",
        actor_id=user.id,
        actor_roles=user.roles,
        target=f"{user.id}",
        extra={"feed_id": feed_id, "paused": payload.paused},
    )
    subs = await database.get_chat_subscriptions(user.id)
    return [rss_subscription_out(sub) for sub in subs]


@router.delete("/rss/{feed_id}", status_code=204)
async def delete_my_rss(
    request: Request,
    user: CurrentUser,
    feed_id: int = Path(description="Feed the subscription points at"),
) -> None:
    if not app_config.rss_enabled:
        raise ApiError(ErrorCode.FEATURE_DISABLED, "RSS is disabled")
    if not await database.is_rss_allowed(user.id):
        raise forbidden(ErrorCode.FORBIDDEN, "RSS is not enabled for this chat")
    write_limiter.check(client_key(request, user.id))

    if not await database.remove_subscription(user.id, feed_id):
        raise not_found(ErrorCode.NOT_FOUND, "Subscription not found")

    audit.record(
        action="me.rss.delete",
        actor_id=user.id,
        actor_roles=user.roles,
        target=f"{user.id}",
        extra={"feed_id": feed_id},
    )


@router.get("/waifu", response_model=WaifuOut)
async def read_my_waifu(user: CurrentUser) -> WaifuOut:
    married_name: str | None = None
    if user.data.married_waifu_id:
        partner = await database.get_user_by_id(user.data.married_waifu_id)
        married_name = partner.full_name if partner else None

    entries: list[WaifuEntryOut] = []
    for chat, _ in await database.get_user_chats(user.id):
        waifu, _is_married = await database.get_user_waifu_in_chat(user.data, chat)
        entries.append(
            WaifuEntryOut(
                chat_id=chat.id,
                chat_title=chat.title,
                waifu_id=waifu.id if waifu else None,
                waifu_name=waifu.full_name if waifu else None,
            )
        )

    return WaifuOut(
        is_married=user.data.is_married,
        married_waifu_id=user.data.married_waifu_id,
        married_waifu_name=married_name,
        entries=entries,
    )


@router.post("/divorce", response_model=WaifuOut)
async def divorce(request: Request, user: CurrentUser) -> WaifuOut:
    """End the caller's marriage and notify the other side."""
    write_limiter.check(client_key(request, user.id))

    try:
        result = await ops.divorce_user(user.id)
    except ValueError as e:
        raise ApiError(ErrorCode.NOT_MARRIED, str(e)) from e

    await _notify_divorce(result, user.data.full_name)

    refreshed = await database.get_user_by_id(user.id)
    if refreshed is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "User disappeared")
    user.data = refreshed
    return await read_my_waifu(user)


async def _notify_divorce(result: ops.DivorceResult, actor_name: str) -> None:
    """Tell the former partner. A blocked bot must not fail the request."""
    try:
        await client.send_message(
            chat_id=result.partner_id,
            text=i18n.t(
                "bot.msg.waifu.divorce_notify", locale=result.partner_lang
            ).format(user=html.escape(actor_name)),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.info(f"webapp: divorce notify to {result.partner_id} failed: {e}")


@router.get("/gifts", response_model=list[GiftOut])
async def list_my_gifts(
    user: CurrentUser,
    sent: bool = Query(False, description="List gifts already given to the bot"),
    limit: int = Query(50, ge=1, le=100),
) -> list[GiftOut]:
    gifts = await database.get_user_gifts(user.id, sent=sent, offset=0, limit=limit)
    return [gift_out(gift) for gift in gifts]


@router.get("/gifts/catalog", response_model=list[GiftCatalogOut])
async def list_gift_catalog(user: CurrentUser) -> list[GiftCatalogOut]:
    del user  # The catalog is public to signed-in users, not to anonymous callers.
    return [
        GiftCatalogOut(
            gift_id=item.id,
            display_name=gift_define.get_display_name(item.id),
            description=item.description,
            comment=item.comment,
            price=item.price,
        )
        for item in gift_define.list_all_gifts()
    ]


@router.post("/gifts/buy", response_model=GiftOut)
async def buy_gift(
    request: Request, payload: GiftPurchaseIn, user: CurrentUser
) -> GiftOut:
    write_limiter.check(client_key(request, user.id))
    try:
        gift_id = gift_define.GiftID(payload.gift_id)
    except ValueError as e:
        raise ApiError(ErrorCode.GIFT_NOT_FOUND, "Gift not found", 404) from e
    if gift_id not in gift_define.ALL_GIFTS:
        # GiftID also contains an internal sentinel used for corrupted legacy rows.
        # It is intentionally not a purchasable catalog item.
        raise ApiError(ErrorCode.GIFT_NOT_FOUND, "Gift not found", 404)
    item = gift_define.get_gift_by_id(gift_id)
    if user.data.user_config.coins < item.price:
        raise ApiError(ErrorCode.INSUFFICIENT_COINS, "Not enough coins", 409)
    gift_entry = await database.buy_gift_for_user(
        user.id, gift_id, rarity=random.randint(1, 5)
    )
    return gift_out(gift_entry)


@router.post("/gifts/{gift_db_id}/send", response_model=GiftUseOut)
async def send_gift(request: Request, gift_db_id: int, user: CurrentUser) -> GiftUseOut:
    write_limiter.check(client_key(request, user.id))
    try:
        result = await send_gift_to_bot(user.id, gift_db_id)
    except ValueError as e:
        message = str(e)
        code = (
            ErrorCode.GIFT_ALREADY_SENT
            if message == "Gift was already sent"
            else ErrorCode.GIFT_NOT_FOUND
            if message == "Gift not found"
            else ErrorCode.FORBIDDEN
        )
        status_code = (
            404
            if code == ErrorCode.GIFT_NOT_FOUND
            else 409
            if code == ErrorCode.GIFT_ALREADY_SENT
            else 403
        )
        raise ApiError(code, message, status_code) from e
    gift_entry = await database.get_gift_by_db_id(gift_db_id)
    assert gift_entry is not None
    return GiftUseOut(gift=gift_out(gift_entry), detail=result.detail)


@router.post("/avatar/refresh")
async def refresh_my_avatar(request: Request, user: CurrentUser) -> dict[str, bool]:
    """Re-download the caller's avatar from Telegram.

    Rate limited separately with a 5 minute cooldown, matching /f5avatar: this hits
    the Telegram API and the result rarely changes.
    """
    write_limiter.check(client_key(request, user.id))

    cooldown_key = f"user_refresh_avatar:{user.id}"
    if await common.memttlcache.get(cooldown_key):
        raise ApiError(ErrorCode.COOLDOWN, "Avatar was refreshed recently")
    await common.memttlcache.set(cooldown_key, True, ttl=300)

    avatar = common.ChatAvatar(user.id)
    ok = await avatar.force_refresh()
    if ok:
        # Drop the cached Telegram file_id so it is re-uploaded on next use.
        await database.update_user_avatar(user.id, None, refreshed=True)
    return {"refreshed": bool(ok)}
