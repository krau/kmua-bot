from dataclasses import dataclass
from datetime import datetime

import pyrogram
from pyrogram.client import Client

from kmua import database, enums
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import state, utils

from .agent import memory_agent, powermemory


@dataclass
class UserMessageGlobal:
    chat_id: int
    message_id: int
    text: str


@dataclass
class GroupMessage:
    chat_id: int
    message_id: int
    text: str
    sender_name: str
    sender_id: int
    date: datetime


async def _cross_memory_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not app_config.agent:
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
    if (
        message.entities is not None
        and message.entities[0].type == pyrogram.enums.MessageEntityType.BOT_COMMAND
    ):
        return False
    text = message.caption or message.text
    if not text or len(text) < 2 or len(text) > 2048:
        return False
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        config = await database.get_chat_config(chat.id)
        if not config.ai_reply:
            return False
    return True


cross_memory_filter = pyrogram.filters.create(_cross_memory_filter_func)


@Client.on_message(cross_memory_filter, group=100)
async def record_memory(client: Client, message: pyrogram.types.Message):
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
    in_group = chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    if app_config.agent_cross_group_memory:
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
                await utils.update_user_memory(memory_agent, texts, user.id)
            # 清空记录
            user_messages = []
        await memttlcache.set(
            state.user_messages_global_key(user.id), user_messages, ttl=86400 * 7
        )
    if app_config.agent_group_memory and powermemory is not None and in_group:
        # 检查群组配置是否启用了群组记忆
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.group_memory_enabled:
            return
        
        group_messages: list[GroupMessage] = await memttlcache.get(
            state.group_messages_key(chat.id), []
        )
        group_messages.append(
            GroupMessage(
                chat_id=chat.id,
                message_id=message.id,
                text=text,
                sender_name=user.full_name or f"{user.id}",
                sender_id=user.id,
                date=message.date or datetime.now(),
            )
        )
        if len(group_messages) > 100:
            group_messages = group_messages[-100:]
            # 每个群组每小时最多通过此函数更新一次记忆
            last_update_key = state.group_memory_update_key(chat.id)
            last_updated = await memttlcache.get(last_update_key)
            if not last_updated:
                logger.debug(
                    f"Updating group memory for chat {chat.id} with {len(group_messages)} messages"
                )
                await memttlcache.set(last_update_key, True, ttl=3600)
                text = "群聊消息记录:\n" + "\n".join(
                    [
                        f"{gm.sender_name}({gm.sender_id})说: {gm.text}"
                        for gm in group_messages
                    ]
                )
                result = await powermemory.add(
                    text, infer=True, user_id=f"group_{chat.id}"
                )
                logger.debug(
                    f"Updated group memory for chat {chat.id}, powermem result: {result}"
                )
            group_messages = []
        await memttlcache.set(
            state.group_messages_key(chat.id), group_messages, ttl=86400 * 7
        )
