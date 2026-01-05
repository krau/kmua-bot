from dataclasses import dataclass

import pyrogram
from pyrogram.client import Client

from kmua import database, enums
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.plugins.agent import state, utils

from .agent import memory_agent


@dataclass
class UserMessageGlobal:
    chat_id: int
    message_id: int
    text: str


async def _cross_memory_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not app_config.agent or not app_config.agent_cross_group_memory:
        return False
    if not message:
        return False
    if not message.from_user or not message.from_user.id:
        return False
    if not message.chat or not message.chat.id:
        return False
    user = message.from_user
    chat = message.chat
    if not chat.id or not user.id:
        return False
    if (
        user.is_bot
        or message.outgoing
        or message.service
        or message.automatic_forward
        or message.forward_from_chat
        or message.forward_from
        or message.forward_sender_name
        or message.via_bot
        or (
            user.id
            in (
                enums.ChatID.ANONYMOUS_ADMIN,
                enums.ChatID.SERVICE_CHAT,
                enums.ChatID.FAKE_CHANNEL,
            )
        )
    ):
        return False
    text = message.caption or message.text
    if not text or len(text) < 12:
        return False
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        config = await database.get_chat_config(chat.id)
        if not config.ai_reply:
            return False
    return True


cross_memory_filter = pyrogram.filters.create(_cross_memory_filter_func)


@Client.on_message(cross_memory_filter, group=100)
async def record_cross_group_memory(client: Client, message: pyrogram.types.Message):
    user = message.from_user
    chat = message.chat
    text = message.caption or message.text
    assert (
        user is not None
        and chat is not None
        and text is not None
        and user.id is not None
        and chat.id is not None
    ), "Invalid message state in record_cross_group_memory"
    user_messages: list[UserMessageGlobal] = await memttlcache.get(
        state.user_messages_global_key(user.id), []
    )
    user_messages.append(
        UserMessageGlobal(
            chat_id=chat.id,
            message_id=message.id,
            text=text,
        )
    )
    if len(user_messages) > 100:
        user_messages = user_messages[-100:]
        # 每个用户每小时最多通过此函数更新一次记忆
        last_update_key = state.user_memory_update_key(user.id)
        last_updated = await memttlcache.get(last_update_key)
        if not last_updated:
            await memttlcache.set(last_update_key, True, ttl=3600)
            texts = "\n".join([um.text for um in user_messages])
            await utils.update_memory(memory_agent, texts, user.id)
    await memttlcache.set(
        state.user_messages_global_key(user.id), user_messages, ttl=86400 * 7
    )
