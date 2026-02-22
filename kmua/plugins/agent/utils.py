import asyncio
import random
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from typing import Any
from weakref import WeakValueDictionary

import pyrogram
from pydantic_ai import (
    Agent,
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ModelRetry,
    UserContent,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.messages import ModelMessage, ModelRequest
from pyrogram.client import Client as PyrogramClient

from kmua import affection, common
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.agent import datatype, state


def get_agent_affection_prompt(rank: float) -> str | None:
    prompts = app_config.agent_affection_prompts
    sorted_ranks = sorted(prompts.keys(), reverse=True)
    for r in sorted_ranks:
        if rank >= float(r):
            return prompts[r]
    return None


async def reply_output(
    client: PyrogramClient, message: pyrogram.types.Message, text: str
):
    if message.chat is None:
        return
    is_group_chat = message.chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    user = message.sender_chat or message.from_user
    lines = [line for line in text.split("\n\n") if line.strip()]
    if not lines:
        return

    max_messages = 2
    total_sentences = len(lines)
    num_messages = min(max_messages, total_sentences)

    base = total_sentences // num_messages
    remainder = total_sentences % num_messages

    chunks: list[str] = []
    index = 0
    for i in range(num_messages):
        size = base + (1 if i < remainder else 0)
        part = lines[index : index + size]
        index += size
        chunks.append("\n".join(part))
    try:
        for chunk in chunks:
            await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
            reply_msg = await message.reply_text(
                chunk, parse_mode=pyrogram.enums.ParseMode.DISABLED
            )
            if reply_msg and is_group_chat and user and user.id:
                bot_reply = datatype.BotLastReply(
                    message_id=reply_msg.id,
                    reply_to_user_id=user.id,
                    reply_to_message_id=message.id,
                    reply_text=chunk,
                    original_user_message=message.text or message.caption or "",
                    timestamp=datetime.now().timestamp(),
                )
                await memttlcache.set(
                    state.bot_last_reply_key(message.chat.id), bot_reply, ttl=300
                )
            await asyncio.sleep(random.uniform(0.721, 3.9))
    except Exception as e:
        logger.error(f"Error replying message: {e.__class__.__name__} - {e}")


class StreamingOutput:
    STREAM_EDIT_INTERVAL = 0.8
    CHAT_ACTION_INTERVAL = 4.5
    MAX_MESSAGE_LENGTH = 4000
    MAX_EDIT_COUNT = 20
    MAX_TOTAL_TIME = 120.0

    def __init__(
        self,
        client: PyrogramClient,
        message: pyrogram.types.Message,
    ):
        self.client = client
        self.message = message
        self.current_text = ""
        self.reply_message: pyrogram.types.Message | None = None
        self.last_edit_time = 0.0
        self.last_chat_action_time = 0.0
        self.edit_count = 0
        self.start_time = 0.0
        self.is_group_chat = message.chat and message.chat.type in (
            pyrogram.enums.ChatType.SUPERGROUP,
            pyrogram.enums.ChatType.GROUP,
        )
        self.user = message.sender_chat or message.from_user
        self._chat_action_task: asyncio.Task | None = None
        self._stop_chat_action = False

    async def _keep_typing_action(self):
        while not self._stop_chat_action:
            try:
                if self.message.chat:
                    await self.client.send_chat_action(
                        chat_id=self.message.chat.id,
                        action=pyrogram.enums.ChatAction.TYPING,
                    )
                await asyncio.sleep(self.CHAT_ACTION_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error sending chat action: {e.__class__.__name__} - {e}")
                break

    def _is_within_limits(self) -> bool:
        current_time = asyncio.get_event_loop().time()
        if self.start_time == 0.0:
            self.start_time = current_time
        elapsed = current_time - self.start_time
        if elapsed > self.MAX_TOTAL_TIME:
            logger.warning(f"Streaming output exceeded max time {self.MAX_TOTAL_TIME}s")
            return False
        if self.edit_count >= self.MAX_EDIT_COUNT:
            logger.warning(
                f"Streaming output exceeded max edit count {self.MAX_EDIT_COUNT}"
            )
            return False
        return True

    async def _send_or_edit(self, text: str, force_new: bool = False):
        if not text.strip():
            return
        if not self._is_within_limits():
            return
        if force_new or self.reply_message is None:
            self._stop_chat_action = False
            if self._chat_action_task is None or self._chat_action_task.done():
                self._chat_action_task = asyncio.create_task(self._keep_typing_action())
            self.reply_message = await self.message.reply_text(
                text[: self.MAX_MESSAGE_LENGTH],
                parse_mode=pyrogram.enums.ParseMode.DISABLED,
            )
            self.current_text = text
            self.edit_count += 1
            if self.reply_message and self.is_group_chat and self.user and self.user.id:
                bot_reply = datatype.BotLastReply(
                    message_id=self.reply_message.id,
                    reply_to_user_id=self.user.id,
                    reply_to_message_id=self.message.id,
                    reply_text=text,
                    original_user_message=self.message.text
                    or self.message.caption
                    or "",
                    timestamp=datetime.now().timestamp(),
                )
                await memttlcache.set(
                    state.bot_last_reply_key(self.message.chat.id),
                    bot_reply,
                    ttl=300,
                )
        else:
            current_time = asyncio.get_event_loop().time()
            if text == self.current_text:
                return
            if (current_time - self.last_edit_time < self.STREAM_EDIT_INTERVAL) and len(
                text
            ) < self.MAX_MESSAGE_LENGTH * 0.8:
                return
            try:
                await self.reply_message.edit_text(
                    text[: self.MAX_MESSAGE_LENGTH],
                    parse_mode=pyrogram.enums.ParseMode.DISABLED,
                )
                self.current_text = text
                self.last_edit_time = current_time
                self.edit_count += 1
            except pyrogram.errors.exceptions.bad_request_400.MessageNotModified:
                pass
            except pyrogram.errors.exceptions.bad_request_400.MessageTooLong:
                await self._send_or_edit(text, force_new=True)

    async def append_delta(self, delta: str):
        if not delta:
            return
        self.current_text += delta
        await self._send_or_edit(self.current_text)

    async def finalize(self):
        self._stop_chat_action = True
        if self._chat_action_task and not self._chat_action_task.done():
            self._chat_action_task.cancel()
            try:
                await self._chat_action_task
            except asyncio.CancelledError:
                pass
        if self.reply_message and self.current_text:
            try:
                await self.reply_message.edit_text(
                    self.current_text[: self.MAX_MESSAGE_LENGTH],
                    parse_mode=pyrogram.enums.ParseMode.DISABLED,
                )
            except pyrogram.errors.exceptions.bad_request_400.MessageNotModified:
                pass
            except Exception as e:
                logger.error(f"Error finalizing message: {e.__class__.__name__} - {e}")


def get_history_text(message_history: list[ModelMessage]) -> str:
    text_lines = []
    for msg in message_history:
        for part in msg.parts:
            match part.part_kind:
                case "user-prompt":
                    if isinstance(part.content, str):
                        text_lines.append(f"[USER]: {part.content}")
                    else:
                        content_text_lines = []
                        for content in part.content:
                            if isinstance(content, str):
                                content_text_lines.append(content)
                        text_lines.append(f"[USER]: {' '.join(content_text_lines)}")
                case "text":
                    if msg.kind == "response":
                        text_lines.append(f"[ASSISTANT]: {part.content}")
                case "tool-call":
                    text_lines.append(
                        f"[TOOL {part.tool_name} CALLED WITH ARGS]: {part.args}"
                    )
                case "tool-return":
                    text_lines.append(
                        f"[TOOL {part.tool_name} RETURNED]: {part.content}"
                    )
                case "retry-prompt":
                    pass
    message_text = "\n".join(text_lines)
    return message_text


async def summarize_history(
    summary_agent: Agent,
    messages: list[ModelMessage],
    messages_threshold: int = app_config.agent_messages_threshold,
) -> list[ModelMessage]:
    # multimodal_content_count = 0
    # for msg in messages:
    #     for part in msg.parts:
    #         if part.part_kind == "user-prompt" and not isinstance(part.content, str):
    #             for content in part.content:
    #                 if not isinstance(content, str):
    #                     multimodal_content_count += 1
    # # 有3条及以上多模态内容时, 强制总结历史消息
    if len(messages) <= messages_threshold:
        return messages

    logger.debug(
        f"Summarizing history: total messages={len(messages)}, messages_threshold={messages_threshold}"
    )
    try:
        messages_to_summarize = messages[:-1]
        current_user_message = messages[-1:]

        message_text = get_history_text(messages_to_summarize)

        summary_result = await summary_agent.run(
            user_prompt=f"{i18n.t('bot.msg.agent.summary_prompt', locale=app_config.lang)}: {message_text}",
            message_history=[],
        )
        logger.debug(f"Agent summarize: {summary_result.output}")
        parts = [UserPromptPart(summary_result.output)]
        if current_user_message[0].kind == "request":
            for part in current_user_message[0].parts:
                if part.part_kind == "user-prompt":
                    parts.append(part)
                # [TODO] handle tool call parts

        return [ModelRequest(parts=parts)]
    except Exception as e:
        logger.exception(
            f"Error summarizing history with agent: {e.__class__.__name__} - {e}"
        )
        filtered_messages = filter_tool_return_if_needed(messages[-messages_threshold:])

        result_messages = []
        for msg in filtered_messages:
            if msg.kind != "request":
                result_messages.append(msg)
                continue

            filtered_parts = []
            for part in msg.parts:
                if part.part_kind == "user-prompt" and not isinstance(
                    part.content, str
                ):
                    continue
                filtered_parts.append(part)

            if filtered_parts:
                new_msg = ModelRequest(parts=filtered_parts)
                result_messages.append(new_msg)

        return result_messages


def filter_tool_return_if_needed(messages: list[ModelMessage]) -> list[ModelMessage]:
    filtered_messages: list[ModelMessage] = []

    tool_calls: defaultdict[str, list[tuple[str, int, ModelMessage]]] = defaultdict(
        list
    )

    for msg_idx, message in enumerate(messages):
        for part in message.parts:
            if part.part_kind == "tool-call" or part.part_kind == "tool-return":
                tool_calls[part.tool_call_id].append((part.part_kind, msg_idx, message))

    messages_to_include = set()

    for tool_call_id, entries in tool_calls.items():
        calls = [e for e in entries if e[0] == "tool-call"]
        returns = [e for e in entries if e[0] == "tool-return"]

        if len(calls) == len(returns) and len(calls) > 0:
            for _, msg_idx, message in entries:
                messages_to_include.add(msg_idx)

    for msg_idx, message in enumerate(messages):
        has_tool_parts = any(
            part.part_kind in ("tool-call", "tool-return") for part in message.parts
        )

        if has_tool_parts:
            if msg_idx in messages_to_include:
                filtered_messages.append(message)
        else:
            filtered_messages.append(message)

    return filtered_messages


_user_memory_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()
_user_memory_locks_lock = asyncio.Lock()


async def _get_user_memory_lock(user_id: int) -> asyncio.Lock:
    async with _user_memory_locks_lock:
        lock = _user_memory_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_memory_locks[user_id] = lock
        return lock


async def update_user_memory(
    agent: Agent[None, datatype.UserMemoryResult],
    message_text: str,
    user_id: int,
):
    lock = await _get_user_memory_lock(user_id)
    async with lock:
        # 每个用户 30 秒内至多更新一次记忆
        # 能超过这个限制的一般是 spammer 了...
        throttle_key = f"user_memory_update_throttle:{user_id}"
        if await memttlcache.get(throttle_key):
            logger.debug(
                f"Skip updating memory for user {user_id} due to 30s rate limit"
            )
            return
        await memttlcache.set(throttle_key, True, ttl=30)

        logger.debug(f"Updating memory for user {user_id}")
        old_memory = await memttlcache.get(f"user_memory_{user_id}")
        if old_memory and isinstance(old_memory, datatype.ChatMemoryy):
            message_text = f"根据已有的记忆和新的聊天消息, 更新对用户的记忆, 并决定对用户的好感变化.\n旧的记忆: {old_memory}\n新的聊天消息: {message_text}"
        memory_result = await agent.run(
            output_type=datatype.UserMemoryResult,
            user_prompt=f"根据以下聊天消息, 总结出关于用户的重要信息, 并决定对用户的好感变化:\n {message_text}",
        )
        logger.debug(f"Agent memory history: {memory_result.output}")
        result = memory_result.output
        try:
            affection_change = result.get_affection_change()
            affection_change += random.randint(-4, 4)
        except ValueError:
            raise ModelRetry(
                "Invalid affection change value from agent, please provide 'affection_option' and 'affection_change_amplitude' fields correctly."
                "The 'affection_option' should be one of 'increase', 'decrease', or 'no_change'."
                "The 'affection_change_amplitude' should be one of 'small', 'medium', or 'large'."
            )
        try:
            if affection_change != 0:
                await affection.update_user_affection(user_id, affection_change)
        except Exception as e:
            logger.exception(f"Error updating user affection: {e}")
        new_memory = result.get_memory()
        if old_memory:
            # 合并记忆列表, 每个字段去重(?), 且限制长度为 3
            for field in datatype.ChatMemoryy.model_fields:
                old_value = getattr(old_memory, field, [])
                new_value = getattr(new_memory, field, [])
                if old_value and new_value:
                    if isinstance(old_value, list) and isinstance(new_value, list):
                        combined = list(dict.fromkeys(old_value + new_value))
                        setattr(new_memory, field, combined[:3])
                    elif isinstance(old_value, str) and isinstance(new_value, str):
                        if new_value not in old_value:
                            combined = [old_value, new_value]
                        else:
                            combined = [old_value]
                        setattr(new_memory, field, combined)
                    elif isinstance(old_value, list) and isinstance(new_value, str):
                        if new_value not in old_value:
                            combined = old_value + [new_value]
                        else:
                            combined = old_value
                        setattr(new_memory, field, combined[:3])
                    elif isinstance(old_value, str) and isinstance(new_value, list):
                        if old_value not in new_value:
                            combined = [old_value] + new_value
                        else:
                            combined = new_value
                        setattr(new_memory, field, combined[:3])
                elif old_value and not new_value:
                    if isinstance(old_value, list):
                        setattr(new_memory, field, old_value[:3])
                    else:
                        setattr(new_memory, field, [old_value])
        await memttlcache.set(
            state.memory_key(user_id),
            new_memory,
            ttl=86400 * 30,  # 30 days
        )


async def update_group_memory():
    pass  # Placeholder for future implementation


async def get_input_prompt(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    include_nearby: int = 0,
    ctx: datatype.ContextInfo | Any | None = None,
) -> list[UserContent]:
    # 公共的单条消息提取逻辑：与原函数一致
    def get_media_and_message(
        m: pyrogram.types.Message,
    ) -> tuple[pyrogram.enums.MessageMediaType | None, pyrogram.types.Message | None]:
        if m.media:
            return m.media, m
        if m.reply_to_message and m.reply_to_message.media:
            return m.reply_to_message.media, m.reply_to_message
        return None, None

    async def build_contents_from_message(
        msg: pyrogram.types.Message,
        ctx_text: str | None = None,
        include_media: bool = True,
    ) -> list[UserContent]:
        contents: list[UserContent] = []
        text_part = f"{ctx_text or ''}\n{msg.text or msg.caption or ''}".strip()
        if text_part:
            contents.append(text_part)

        media, media_message = get_media_and_message(msg)
        if media and media_message and app_config.agent_multimodal and include_media:
            match media:
                case pyrogram.enums.MessageMediaType.PHOTO:
                    photo = media_message.photo
                    if (
                        "photo" in app_config.agent_multimodal_inputs
                        and photo
                        and photo.file_id
                    ):
                        photo_file = await client.download_media(
                            message=photo.file_id, in_memory=True
                        )
                        if isinstance(photo_file, BytesIO):
                            contents.append(
                                BinaryContent(
                                    data=photo_file.getvalue(),
                                    media_type="image/jpeg",
                                )
                            )
                case pyrogram.enums.MessageMediaType.VIDEO:
                    video = media_message.video
                    if (
                        video
                        and video.file_id
                        and video.mime_type
                        and video.file_size
                        and video.file_size <= 20 * 1024 * 1024
                    ):
                        if "video" in app_config.agent_multimodal_inputs:
                            video_file = await client.download_media(
                                message=video.file_id, in_memory=True
                            )
                            if isinstance(video_file, BytesIO):
                                contents.append(
                                    BinaryContent(
                                        data=video_file.getvalue(),
                                        media_type=video.mime_type,
                                    )
                                )
                case pyrogram.enums.MessageMediaType.DOCUMENT:
                    document = media_message.document
                    if (
                        document
                        and document.file_id
                        and document.mime_type
                        and document.file_size <= 10 * 1024 * 1024
                    ):
                        if document.mime_type in app_config.agent_multimodal_inputs:
                            doc_file = await client.download_media(
                                message=document.file_id, in_memory=True
                            )
                            if isinstance(doc_file, BytesIO):
                                contents.append(
                                    BinaryContent(
                                        data=doc_file.getvalue(),
                                        media_type=document.mime_type,
                                    )
                                )
                        elif (
                            document.mime_type.startswith("image/")
                            and "photo" in app_config.agent_multimodal_inputs
                        ):
                            doc_file = await client.download_media(
                                message=document.file_id, in_memory=True
                            )
                            if isinstance(doc_file, BytesIO):
                                contents.append(
                                    BinaryContent(
                                        data=doc_file.getvalue(),
                                        media_type=document.mime_type,
                                    )
                                )
        return contents

    user_prompt: list[UserContent] = []

    # 处理回复消息链：从当前消息向上追溯
    reply_chain: list[pyrogram.types.Message] = []
    current = message
    while current.reply_to_message and len(reply_chain) < 10:  # 最多10条消息链
        reply_chain.append(current.reply_to_message)
        current = current.reply_to_message
    reply_chain.reverse()  # 反转，使其按时间顺序排列

    # include_nearby > 0 时，先追加前面 N 条消息（从旧到新）
    if include_nearby and include_nearby > 0 and message.chat and message.chat.id:
        # 构建需要获取的消息ID列表
        message_ids = []
        base_id = message.id
        for i in range(include_nearby):
            mid = base_id - (i + 1)
            if mid > 0:
                message_ids.append(mid)
        message_ids.reverse()  # 反转以按时间顺序获取

        if message_ids:
            # 从缓存中获取消息对象，未命中则从API获取
            prev_msgs = await common.tgmethod.get_cached_messages_objects(
                message.chat.id, message_ids
            )
            media_count = 0
            for prev_msg in prev_msgs:
                sender_name = "未知用户"
                if prev_msg.from_user:
                    sender_name = prev_msg.from_user.first_name or "未知用户"
                elif prev_msg.sender_chat:
                    sender_name = prev_msg.sender_chat.title or "未知频道"
                include_media = True
                if media_count >= 2:
                    include_media = False
                if prev_msg.media:
                    media_count += 1
                user_prompt.extend(
                    await build_contents_from_message(
                        prev_msg,
                        f"[群聊上下文 - {sender_name}]",
                        include_media=include_media,
                    )
                )

    # 处理回复消息链，只在最后一条消息中包含媒体
    if reply_chain:
        for idx, reply_msg in enumerate(reply_chain):
            is_last = idx == len(reply_chain) - 1
            sender_name = "未知用户"
            if reply_msg.from_user:
                sender_name = reply_msg.from_user.first_name or "未知用户"
            elif reply_msg.sender_chat:
                sender_name = reply_msg.sender_chat.title or "未知频道"
            user_prompt.extend(
                await build_contents_from_message(
                    reply_msg,
                    f"[回复链消息 - {sender_name}]",
                    include_media=is_last,
                )
            )

    # 最后追加当前消息（带 ctx）
    user_prompt.extend(
        await build_contents_from_message(
            message, ctx_text=str(ctx) if ctx else None, include_media=True
        )
    )

    return user_prompt


def has_multimodal_input(user_prompt: list[UserContent]) -> bool:
    for content in user_prompt:
        if isinstance(
            content, (ImageUrl | AudioUrl | DocumentUrl | VideoUrl | BinaryContent)
        ):
            return True
    return False
