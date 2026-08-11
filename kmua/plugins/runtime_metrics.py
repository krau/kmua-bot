"""Low-priority, payload-free Telegram update throughput observation."""

from pyrogram import Client

from kmua.webapp.metrics import runtime_metrics


@Client.on_raw_update(group=999)
async def observe_telegram_update(client, update, users, chats) -> None:
    """Aggregate raw group events; no second parsed-handler dispatch is required."""
    runtime_metrics.observe_telegram_update(type(update).__name__)
    message = getattr(update, "message", None)
    peer = (
        getattr(message, "peer_id", None)
        if message is not None
        else getattr(update, "peer", None)
    )
    chat_id = _chat_id(peer)
    if chat_id is None:
        return
    text = getattr(message, "message", "") if message is not None else ""
    command = text.split(maxsplit=1)[0].partition("@")[0].removeprefix("/").lower()
    feature = _FEATURE_COMMANDS.get(command)
    if feature is None and type(update).__name__ == "UpdateBotCallbackQuery":
        feature = "callback"
    runtime_metrics.observe_group_activity(chat_id, feature)


def _chat_id(peer) -> int | None:
    """Convert raw Telegram group peers to the IDs stored by kmua."""
    channel_id = getattr(peer, "channel_id", None)
    if isinstance(channel_id, int):
        return -100_000_000_0000 - channel_id
    chat_id = getattr(peer, "chat_id", None)
    if isinstance(chat_id, int):
        return -chat_id
    return None


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
