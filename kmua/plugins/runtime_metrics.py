"""Low-priority, payload-free Telegram update throughput observation."""

from pyrogram import Client, filters

from kmua.webapp.metrics import runtime_metrics


@Client.on_raw_update(group=999)
async def observe_telegram_update(client, update, users, chats) -> None:
    """Record update class only; this never retains payloads or identities."""
    runtime_metrics.observe_telegram_update(type(update).__name__)


_FEATURE_COMMANDS = {
    "bottle": "bottle_throw",
    "throwbottle": "bottle_throw",
    "pickbottle": "bottle_pick",
    "config": "group_config",
    "syncmembers": "member_sync",
    "infographic": "infographic",
    "greet": "greeting_config",
    "chat": "ai_chat",
}


@Client.on_message(filters.group, group=999)
async def observe_group_message(client, message) -> None:
    """Count group activity and recognized commands; discard content immediately."""
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    command = text.split(maxsplit=1)[0].partition("@")[0].removeprefix("/").lower()
    runtime_metrics.observe_group_activity(chat_id, _FEATURE_COMMANDS.get(command))


@Client.on_callback_query(group=999)
async def observe_callback(client, callback_query) -> None:
    """Count group callback activity without retaining callback data."""
    if callback_query.message and callback_query.message.chat:
        runtime_metrics.observe_group_activity(callback_query.message.chat.id, "callback")
