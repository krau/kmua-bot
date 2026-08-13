from dataclasses import dataclass
from datetime import UTC, datetime

import pyrogram
from pyrogram.client import Client

from kmua import database, enums
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import state
from kmua.plugins.agent.user_memory import update_user_memory

from .agent import memory_agent, powermemory
from .myfilter import (
    base_filter,
    mention_me_filter,
    not_bottle_reply_filter,
    reply_me_filter,
)
from .whitelist import is_chat_allowed

_AGENT_MEMORY_TRIGGER_COUNT = 100


@dataclass
class UserMessageGlobal:
    chat_id: int
    message_id: int
    text: str


@dataclass
class AgentMessage:
    chat_id: int
    chat_name: str
    is_group: bool
    date: datetime
    text: str


@dataclass
class GroupMessage:
    chat_id: int
    message_id: int
    text: str
    sender_name: str
    sender_id: int
    date: datetime


async def _base_memory_filter_func(
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
    if not is_chat_allowed(chat.id):
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
    if not text or len(text) < 2 or len(text) > 2048:
        return False
    return True


base_memory_filter = pyrogram.filters.create(_base_memory_filter_func)

agent_memory_filter = (
    base_memory_filter
    & base_filter
    & (reply_me_filter | pyrogram.filters.private | mention_me_filter)
    & not_bottle_reply_filter
)

group_memory_filter = base_memory_filter & pyrogram.filters.group


def format_user_messages(messages: list[AgentMessage]) -> str:
    """按聊天分组、带时间戳的紧凑格式, 供 memory agent 阅读。"""
    if not messages:
        return ""
    grouped: dict[int, list[AgentMessage]] = {}
    for msg in messages:
        grouped.setdefault(msg.chat_id, []).append(msg)
    parts: list[str] = ["用户与 AI 的聊天记录(按聊天分组, 时间为 UTC):"]
    for msgs in grouped.values():
        first = msgs[0]
        header = "私聊" if not first.is_group else f"群聊「{first.chat_name}」"
        parts.append(f"[{header}]")
        for msg in msgs:
            text = msg.text.replace("\n", " ")
            parts.append(f"  {msg.date:%Y-%m-%d %H:%M} {text}")
    return "\n".join(parts)


@Client.on_message(base_memory_filter, group=100)
async def record_memory(client: Client, message: pyrogram.types.Message):
    if not app_config.agent or not app_config.agent_cross_group_memory:
        return
    user = message.from_user
    chat = message.chat
    text = message.caption or message.text
    assert (
        user is not None
        and chat is not None
        and text is not None
        and user.id is not None
        and chat.id is not None
    ), "Invalid message state in record_memory"
    if not is_chat_allowed(chat.id):
        return
    in_group = chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    if in_group:
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.ai_reply:
            return

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
            if memory_agent is not None:
                await update_user_memory(memory_agent, texts, user.id)
        # 清空记录
        user_messages = []
    await memttlcache.set(
        state.user_messages_global_key(user.id), user_messages, ttl=86400 * 7
    )


@Client.on_message(agent_memory_filter, group=100)
async def record_agent_memory(client: Client, message: pyrogram.types.Message):
    if not app_config.agent:
        return
    user = message.from_user
    chat = message.chat
    text = message.caption or message.text
    assert (
        user is not None
        and chat is not None
        and text is not None
        and user.id is not None
        and chat.id is not None
    ), "Invalid message state in record_agent_memory"
    if not is_chat_allowed(chat.id):
        return
    in_group = chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    if in_group:
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.ai_reply:
            return
        chat_name = chat.title or f"chat {chat.id}"
    else:
        chat_name = ""

    agent_messages: list[AgentMessage] = await memttlcache.get(
        state.agent_messages_key(user.id), []
    )
    agent_messages.append(
        AgentMessage(
            chat_id=chat.id,
            chat_name=chat_name,
            is_group=in_group,
            date=message.date or datetime.now(UTC),
            text=text,
        )
    )
    if len(agent_messages) >= _AGENT_MEMORY_TRIGGER_COUNT:
        agent_messages = agent_messages[-_AGENT_MEMORY_TRIGGER_COUNT:]
        # 每个用户每小时最多通过此函数更新一次记忆
        last_update_key = state.agent_memory_update_key(user.id)
        last_updated = await memttlcache.get(last_update_key)
        if not last_updated:
            await memttlcache.set(last_update_key, True, ttl=3600)
            if memory_agent is not None:
                await update_user_memory(
                    memory_agent, format_user_messages(agent_messages), user.id
                )
            agent_messages = []
        # 小时额度已用完: 保留最近 100 条, 下次触发时再提交, 不丢弃已记录内容
    await memttlcache.set(
        state.agent_messages_key(user.id), agent_messages, ttl=86400 * 7
    )


@Client.on_message(group_memory_filter, group=100)
async def record_group_memory(client: Client, message: pyrogram.types.Message):
    if not app_config.agent or not app_config.agent_group_memory:
        return
    if powermemory is None:
        return
    user = message.from_user
    chat = message.chat
    text = message.caption or message.text
    assert (
        user is not None
        and chat is not None
        and text is not None
        and user.id is not None
        and chat.id is not None
    ), "Invalid message state in record_group_memory"
    if not is_chat_allowed(chat.id):
        return
    # 利用缓存的 chat config，避免重复 DB 查询
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config.ai_reply or not chat_config.group_memory_enabled:
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
            date=message.date or datetime.now(UTC),
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
            result = await powermemory.add(text, infer=True, user_id=f"group_{chat.id}")
            logger.debug(
                f"Updated group memory for chat {chat.id}, powermem result: {result}"
            )
        group_messages = []
    await memttlcache.set(
        state.group_messages_key(chat.id), group_messages, ttl=86400 * 7
    )
