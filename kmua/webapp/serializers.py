"""Model-to-schema conversion.

Shared so the same database row always renders the same way, whichever router
returns it.
"""

from __future__ import annotations

from datetime import datetime

from kmua.config import app_config
from kmua.database.models import (
    ChatConfig,
    ChatData,
    Quote,
    RssSubscription,
    UserData,
)
from kmua.webapp.schemas import (
    AdminChatOut,
    AdminUserOut,
    ChatConfigOut,
    QuoteOut,
    RssSubscriptionOut,
    VerifyQuestionOut,
)


def timestamp(value: datetime | None) -> str:
    """Render a timestamp as ISO 8601, or an empty string when unset.

    The frontend formats dates with `Intl.DateTimeFormat` in the user's locale, so
    the API only has to be unambiguous.
    """
    return value.isoformat() if value is not None else ""


def quote_out(quote: Quote, chat_title: str | None = None) -> QuoteOut:
    # `quote.user` is lazy="noload", so it is only populated when the query asked
    # for it. Reading the attribute directly would raise outside a session.
    user_name: str | None = None
    loaded_user = quote.__dict__.get("user")
    if isinstance(loaded_user, UserData):
        user_name = loaded_user.full_name

    return QuoteOut(
        link=quote.link,
        chat_id=quote.chat_id,
        chat_title=chat_title,
        user_id=quote.user_id,
        user_name=user_name,
        message_id=quote.message_id,
        text=quote.text,
        has_image=bool(quote.img),
        created_at=timestamp(quote.created_at),
    )


def chat_config_out(config: ChatConfig) -> ChatConfigOut:
    return ChatConfigOut(
        waifu_enabled=config.waifu_enabled,
        delete_events_enabled=config.delete_events_enabled,
        unpin_channel_pin_enabled=config.unpin_channel_pin_enabled,
        quote_probability=config.quote_probability,
        quote_pin_message=config.quote_pin_message,
        title_permissions=_normalize_permissions(config.title_permissions),
        greeting=config.greeting,
        ai_reply=config.ai_reply,
        ai_reply_other_bots_enabled=config.ai_reply_other_bots_enabled,
        ai_comment=config.ai_comment,
        setu_enabled=config.setu_enabled,
        convert_b23_enabled=config.convert_b23_enabled,
        parse_links_enabled=config.parse_links_enabled,
        parse_artwork_enabled=config.parse_artwork_enabled,
        parse_sites_enabled=config.parse_sites_enabled,
        pick_bottle_enabled=config.pick_bottle_enabled,
        group_memory_enabled=config.group_memory_enabled,
        sticker_memory_enabled=config.sticker_memory_enabled,
        parse_wechat_enabled=config.parse_wechat_enabled,
        rss_agent_summary=config.rss_agent_summary,
        rss_agent_broadcast=config.rss_agent_broadcast,
        verify_enabled=config.verify_enabled,
        verify_strategy=config.verify_strategy,
        verify_method=config.verify_method,
        verify_max_attempts=config.verify_max_attempts,
        verify_timeout_seconds=config.verify_timeout_seconds,
        verify_fail_action=config.verify_fail_action,
        verify_questions=[
            VerifyQuestionOut.model_validate(q) for q in config.verify_questions
        ],
        lang=config.lang,
    )


def _normalize_permissions(raw: dict | str | None) -> dict[str, bool]:
    """Coerce stored title permissions into a plain bool map.

    Some older rows hold a JSON string rather than an object (see the warning in
    plugins/title/title.py), so both shapes have to be tolerated on read.
    """
    if raw is None:
        return {}
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        raw = parsed if isinstance(parsed, dict) else {}
    return {str(key): bool(value) for key, value in raw.items()}


def admin_chat_out(chat: ChatData, member_count: int) -> AdminChatOut:
    return AdminChatOut(
        id=chat.id,
        title=chat.title,
        username=chat.username,
        member_count=member_count,
        created_at=timestamp(chat.created_at),
        is_blocked=chat.is_blocked,
    )


def admin_user_out(user: UserData) -> AdminUserOut:
    config = user.user_config
    return AdminUserOut(
        id=user.id,
        full_name=user.full_name,
        username=user.username,
        lang=config.lang,
        coins=config.coins,
        affection=config.affection,
        waifu_mention=user.waifu_mention,
        is_bot=user.is_bot,
        is_real_user=user.is_real_user,
        is_bot_global_admin=user.is_bot_global_admin,
        is_blocked=user.is_blocked,
        is_owner=user.id in app_config.owners,
        is_married=user.is_married,
        married_waifu_id=user.married_waifu_id,
        created_at=timestamp(user.created_at),
    )


def rss_subscription_out(sub: RssSubscription) -> RssSubscriptionOut:
    return RssSubscriptionOut(
        id=sub.id,
        feed_id=sub.feed_id,
        url=sub.feed.url,
        title=sub.feed.title,
        paused=sub.paused,
        interval_minutes=sub.interval_minutes,
        last_error=sub.feed.last_error,
        last_fetched_at=timestamp(sub.feed.last_fetched_at),
        created_at=timestamp(sub.created_at),
    )
