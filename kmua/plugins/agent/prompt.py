import asyncio
import mimetypes
from datetime import datetime
from io import BytesIO
from typing import Any

import pyrogram
from pydantic_ai import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.messages import (
    MULTI_MODAL_CONTENT_TYPES,
    ModelMessage,
    ModelRequest,
)
from pyrogram.client import Client as PyrogramClient

from kmua import affection, common
from kmua.common.memory_store import memttlcache
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state


def _utf16_len(s: str) -> int:
    """Return the UTF-16 code unit length of a Python str (surrogates counted as 2)."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def _utf16_slice(s: str, start: int, end: int) -> str:
    """Slice *s* by UTF-16 code unit offsets [start, end)."""
    result: list[str] = []
    pos = 0
    for ch in s:
        if pos >= end:
            break
        width = 2 if ord(ch) > 0xFFFF else 1
        if pos >= start:
            result.append(ch)
        pos += width
    return "".join(result)


def entities_to_markdown(
    text: str,
    entities: list[pyrogram.types.MessageEntity] | None,
) -> str:
    """Flatten Telegram message entities into a Markdown-like string.

    Supported conversions:
    - TEXT_LINK      → [label](url)
    - TEXT_MENTION   → [name](tg://user?id=...)
    - BOLD           → **text**
    - ITALIC         → _text_
    - CODE           → `text`
    - PRE            → ```lang\\ntext\\n```
    - STRIKETHROUGH  → ~~text~~
    - SPOILER        → ||text||
    - BLOCKQUOTE     → > text  (per line)

    All other entity types are left as plain text.
    Overlapping/nested entities are handled by processing them in offset order
    and tracking the current UTF-16 cursor.
    """
    if not entities:
        return text

    E = pyrogram.enums.MessageEntityType

    # Sort by offset ascending, then by length descending so larger spans
    # come first when two entities start at the same offset.
    sorted_entities = sorted(entities, key=lambda e: (e.offset, -e.length))

    parts: list[str] = []
    # UTF-16 cursor tracking
    cursor: int = 0  # current position in UTF-16 code units
    total_utf16 = _utf16_len(text)

    for entity in sorted_entities:
        e_start = entity.offset
        e_end = entity.offset + entity.length

        # Clamp to valid range
        if e_start >= total_utf16:
            continue
        e_end = min(e_end, total_utf16)

        # If this entity starts before our cursor it overlaps a previous one;
        # skip to avoid corrupted markdown (overlapping is rare in practice).
        if e_start < cursor:
            continue

        # Append literal text between cursor and this entity
        if e_start > cursor:
            parts.append(_utf16_slice(text, cursor, e_start))

        span = _utf16_slice(text, e_start, e_end)

        match entity.type:
            case E.TEXT_LINK:
                url = entity.url or ""
                parts.append(f"[{span}]({url})")
            case E.TEXT_MENTION:
                user_id = entity.user.id if entity.user else 0
                name = span
                parts.append(f"[{name}](tg://user?id={user_id})")
            case E.BOLD:
                parts.append(f"**{span}**")
            case E.ITALIC:
                parts.append(f"_{span}_")
            case E.CODE:
                parts.append(f"`{span}`")
            case E.PRE:
                lang = entity.language or ""
                parts.append(f"```{lang}\n{span}\n```")
            case E.STRIKETHROUGH:
                parts.append(f"~~{span}~~")
            case E.SPOILER:
                parts.append(f"||{span}||")
            case E.BLOCKQUOTE:
                quoted = "\n".join(f"> {line}" for line in span.splitlines())
                parts.append(quoted)
            case _:
                parts.append(span)

        cursor = e_end

    # Append any remaining text after the last entity
    if cursor < total_utf16:
        parts.append(_utf16_slice(text, cursor, total_utf16))

    return "".join(parts)


async def _download_media_with_timeout(
    client: PyrogramClient,
    file_id: str,
    timeout: int | None = None,
) -> BytesIO | None:
    """Download media with optional timeout to prevent long blocking.

    Args:
        client: Pyrogram client
        file_id: File ID to download
        timeout: Timeout in seconds (None means use config default, 0 means no timeout)

    Returns:
        BytesIO object or None if download failed/timed out
    """
    timeout_val = timeout if timeout is not None else app_config.agent_download_timeout

    try:
        if timeout_val > 0:
            result = await asyncio.wait_for(
                client.download_media(message=file_id, in_memory=True),
                timeout=timeout_val,
            )
        else:
            result = await client.download_media(message=file_id, in_memory=True)

        if isinstance(result, BytesIO):
            return result
        return None
    except TimeoutError:
        logger.warning(
            f"Download timed out after {timeout_val}s for file_id: {file_id[:20]}..."
        )
        return None
    except Exception as e:
        logger.debug(f"Download failed: {e.__class__.__name__}: {e}")
        return None


def get_agent_affection_prompt(rank: float) -> str | None:
    prompts = app_config.agent_affection_prompts
    sorted_ranks = sorted(prompts.keys(), reverse=True)
    for r in sorted_ranks:
        if rank >= float(r):
            return prompts[r]
    return None


async def get_input_prompt(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    include_nearby: int = 0,
    ctx: datatype.ContextInfo | Any | None = None,
) -> tuple[list[UserContent], bool]:
    """Build the user prompt list and return whether the current message itself
    contains media that requires multimodal understanding.

    The second element is True only when the *current* message (or its direct
    reply_to_message) contributed a BinaryContent item — nearby group context
    messages and deep reply-chain entries are intentionally excluded so that the
    smart text model is not swapped out just because unrelated media exists nearby.
    """

    def sender_label(sender: Any) -> str:
        """Label a message sender as 'name(id)' so history recall can tell
        speakers apart in shared group conversations."""
        if sender is None:
            return "未知用户"
        name = (
            getattr(sender, "first_name", None)
            or getattr(sender, "title", None)
            or "未知用户"
        )
        sender_id = getattr(sender, "id", None)
        if sender_id is None:
            return name
        return f"{name}({sender_id})"

    # 公共的单条消息提取逻辑：只获取当前消息本身的媒体，不获取回复消息的媒体
    def get_media_and_message(
        m: pyrogram.types.Message,
    ) -> tuple[pyrogram.enums.MessageMediaType | None, pyrogram.types.Message | None]:
        if m.media:
            return m.media, m
        return None, None

    async def build_contents_from_message(
        msg: pyrogram.types.Message,
        ctx_text: str | None = None,
        include_media: bool = True,
    ) -> list[UserContent]:
        contents: list[UserContent] = []
        raw_text = msg.text or msg.caption or ""
        entities = msg.entities or msg.caption_entities
        formatted_text = entities_to_markdown(raw_text, entities)
        text_part = f"{ctx_text or ''}\n{formatted_text}".strip()
        if text_part:
            contents.append(text_part)

        media, media_message = get_media_and_message(msg)

        # Poll: pure-text representation, no multimodal config required
        if (
            media == pyrogram.enums.MessageMediaType.POLL
            and media_message
            and media_message.poll
        ):
            poll = media_message.poll
            poll_type = "quiz" if poll.type == pyrogram.enums.PollType.QUIZ else "poll"
            poll_status = "closed" if poll.is_closed else "active"
            lines = [
                f"[{poll_type}|{poll_status}"
                f"|voters:{poll.total_voter_count}"
                f"{'|multiple_choice' if poll.allows_multiple_answers else ''}"
                f"{'|anonymous' if poll.is_anonymous else ''}]",
                f"Q: {poll.question}",
            ]
            for i, opt in enumerate(poll.options or []):
                marker = ""
                if poll.correct_option_ids is not None and i in poll.correct_option_ids:
                    marker = " ✓"
                lines.append(f"  {i + 1}. {opt.text} ({opt.voter_count} votes){marker}")
            if poll.explanation:
                lines.append(f"Explanation: {poll.explanation}")
            contents.append("\n".join(lines))

        if media and media_message and app_config.agent_multimodal and include_media:
            match media:
                case pyrogram.enums.MessageMediaType.PHOTO:
                    photo = media_message.photo
                    if (
                        "photo" in app_config.agent_multimodal_inputs
                        and photo
                        and photo.file_id
                    ):
                        photo_file = await _download_media_with_timeout(
                            client, photo.file_id
                        )
                        if photo_file:
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
                            video_file = await _download_media_with_timeout(
                                client, video.file_id
                            )
                            if video_file:
                                contents.append(
                                    BinaryContent(
                                        data=video_file.getvalue(),
                                        media_type=video.mime_type,
                                    )
                                )
                case pyrogram.enums.MessageMediaType.AUDIO:
                    audio = media_message.audio
                    if (
                        audio
                        and audio.file_id
                        and audio.mime_type
                        and audio.file_size
                        and audio.file_size <= 10 * 1024 * 1024
                    ):
                        if "audio" in app_config.agent_multimodal_inputs:
                            audio_file = await _download_media_with_timeout(
                                client, audio.file_id
                            )
                            if audio_file:
                                contents.append(
                                    BinaryContent(
                                        data=audio_file.getvalue(),
                                        media_type=audio.mime_type,
                                    )
                                )
                case pyrogram.enums.MessageMediaType.VOICE:
                    voice = media_message.voice
                    if (
                        voice
                        and voice.file_id
                        and voice.mime_type
                        and voice.file_size
                        and voice.file_size <= 10 * 1024 * 1024
                    ):
                        if "audio" in app_config.agent_multimodal_inputs:
                            voice_file = await _download_media_with_timeout(
                                client, voice.file_id
                            )
                            if voice_file:
                                contents.append(
                                    BinaryContent(
                                        data=voice_file.getvalue(),
                                        media_type=voice.mime_type,
                                    )
                                )
                case pyrogram.enums.MessageMediaType.DOCUMENT:
                    document = media_message.document
                    if (
                        document
                        and document.file_id
                        and document.file_size <= 10 * 1024 * 1024
                    ):
                        mime_type = document.mime_type
                        # .txt tg 返回的是 'text/plain; charset=utf-8'
                        # markdown 返回的却是 'text/markdown'...
                        if not mime_type:
                            thetype, _ = mimetypes.guess_type(document.file_name)
                            mime_type = thetype or "application/octet-stream"
                        if mime_type.split(";")[0].startswith("text/"):
                            doc_file = await _download_media_with_timeout(
                                client, document.file_id
                            )
                            if doc_file:
                                try:
                                    text = doc_file.getvalue().decode("utf-8")
                                    contents.append(text)
                                except UnicodeDecodeError:
                                    pass
                        elif mime_type in app_config.agent_multimodal_inputs:
                            doc_file = await _download_media_with_timeout(
                                client, document.file_id
                            )
                            if doc_file:
                                contents.append(
                                    BinaryContent(
                                        data=doc_file.getvalue(),
                                        media_type=mime_type,
                                    )
                                )
                        elif (
                            document.mime_type.startswith("image/")
                            and "photo" in app_config.agent_multimodal_inputs
                        ):
                            doc_file = await _download_media_with_timeout(
                                client, document.file_id
                            )
                            if doc_file:
                                contents.append(
                                    BinaryContent(
                                        data=doc_file.getvalue(),
                                        media_type=document.mime_type,
                                    )
                                )
                case pyrogram.enums.MessageMediaType.STICKER:
                    sticker = media_message.sticker
                    if (
                        sticker
                        and sticker.file_id
                        and "photo" in app_config.agent_multimodal_inputs
                    ):
                        if sticker.is_animated:
                            pass
                        elif sticker.is_video:
                            sticker_file = await _download_media_with_timeout(
                                client, sticker.file_id
                            )
                            if sticker_file:
                                frame = await common.webm_first_frame(
                                    sticker_file.getvalue()
                                )
                                if frame:
                                    contents.append(
                                        BinaryContent(
                                            data=frame,
                                            media_type="image/webp",
                                        )
                                    )
                        else:
                            sticker_file = await _download_media_with_timeout(
                                client, sticker.file_id
                            )
                            if sticker_file:
                                contents.append(
                                    BinaryContent(
                                        data=sticker_file.getvalue(),
                                        media_type="image/webp",
                                    )
                                )
        return contents

    user_prompt: list[UserContent] = []
    seen_msg_ids: set[int] = set()

    # 处理回复消息链：从当前消息向上追溯
    # 注意：在话题群组中，需要检查是否是真正的用户回复
    reply_chain: list[pyrogram.types.Message] = []
    current = message
    while len(reply_chain) < 10:
        # 检查是否是明确的用户回复（非话题自动回复）
        if not is_explicit_reply(current):
            break
        if not current.reply_to_message:
            break
        reply_chain.append(current.reply_to_message)
        current = current.reply_to_message
    reply_chain.reverse()

    # 检测回复链是否是 bot 与用户交替对话的历史记录（已存在于 message history 中）。
    # 判定规则：链上奇数位置（bot 发送，回复用户）和偶数位置（用户发送，回复 bot）
    # 交替出现，遍历完整链（短链）或连续满足条件达到深度 6（长链）即判定成立。
    # 判定成立时截断为只保留最后一条（用户直接回复的那条 bot 消息），避免与
    # message history 重复。
    _HISTORY_CHAIN_CHECK_DEPTH = 6
    bot_id = client.me.id if client.me else None
    if bot_id is not None and len(reply_chain) >= 2:
        # reply_chain 已是从旧到新排列。
        # 从新到旧遍历更直观：reply_chain[-1] 是用户直接回复的消息（应为 bot 发的），
        # reply_chain[-2] 是再上一条（应为用户发的），以此类推。
        is_history_chain = True
        check_depth = 0
        # 从链尾（最新）往前，成对检查 [bot消息, 用户消息]
        for i in range(len(reply_chain) - 1, 0, -2):
            bot_msg = reply_chain[i]  # 较新，应为 bot 发送
            user_msg = reply_chain[i - 1]  # 较旧，应为用户发送
            bot_msg_is_bot = (
                bot_msg.from_user is not None and bot_msg.from_user.id == bot_id
            )
            user_msg_is_user = (
                user_msg.from_user is None or user_msg.from_user.id != bot_id
            )
            if not bot_msg_is_bot or not user_msg_is_user:
                is_history_chain = False
                break
            check_depth += 1
            if check_depth >= _HISTORY_CHAIN_CHECK_DEPTH:
                break  # 连续满足 6 层，视为判定成立
        if is_history_chain:
            # 只保留最后一条（用户直接回复的 bot 消息）
            reply_chain = reply_chain[-1:]

    has_reply = bool(reply_chain)

    # include_nearby > 0 时，先追加前面 N 条消息（从旧到新）
    if include_nearby and include_nearby > 0 and message.chat and message.chat.id:
        message_ids = []
        base_id = message.id
        for i in range(include_nearby):
            mid = base_id - i - 1
            if mid > 0:
                message_ids.append(mid)
        message_ids.reverse()

        if message_ids:
            prev_msgs = await common.get_cached_messages_objects(
                message.chat.id, message_ids
            )
            closest_media_msg: pyrogram.types.Message | None = None
            for prev_msg in reversed(prev_msgs):
                if prev_msg.media and not closest_media_msg:
                    closest_media_msg = prev_msg
                    break
            for prev_msg in prev_msgs:
                if prev_msg.id in seen_msg_ids:
                    continue
                seen_msg_ids.add(prev_msg.id)
                sender_name = sender_label(prev_msg.from_user or prev_msg.sender_chat)
                include_media = (
                    not has_reply
                    and closest_media_msg is not None
                    and prev_msg.id == closest_media_msg.id
                )
                user_prompt.extend(
                    await build_contents_from_message(
                        prev_msg,
                        f"[群聊消息|发送者:{sender_name}|消息ID:{prev_msg.id}]",
                        include_media=include_media,
                    )
                )

    # 处理回复消息链，只在最后一条（当前消息直接回复的）中包含媒体
    if reply_chain:
        last_idx = len(reply_chain) - 1
        for idx, reply_msg in enumerate(reply_chain):
            if reply_msg.id in seen_msg_ids:
                continue
            seen_msg_ids.add(reply_msg.id)
            sender_name = sender_label(reply_msg.from_user or reply_msg.sender_chat)
            user_prompt.extend(
                await build_contents_from_message(
                    reply_msg,
                    f"[被引用的消息|发送者:{sender_name}|消息ID:{reply_msg.id}]",
                    include_media=(idx == last_idx),
                )
            )

    # 最后追加当前消息（带 ctx），并检测是否含有需要多模态理解的媒体
    sender = message.sender_chat or message.from_user
    sender_name = sender_label(sender)
    current_msg_label = f"[当前消息|发送者:{sender_name}|消息ID:{message.id}]"
    if ctx is None:
        ctx_str = ""
    elif isinstance(ctx, datatype.ContextInfo):
        ctx_str = ctx.to_text()
    elif isinstance(ctx, dict):
        ctx_str = "\n".join(f"{k}: {v}" for k, v in ctx.items() if v is not None)
    else:
        ctx_str = str(ctx)
    ctx_text = f"{current_msg_label}\n{ctx_str}" if ctx_str else current_msg_label
    user_prompt.extend(
        await build_contents_from_message(
            message, ctx_text=ctx_text, include_media=True
        )
    )
    needs_multimodal = any(
        isinstance(item, (ImageUrl, AudioUrl, DocumentUrl, VideoUrl, BinaryContent))
        for item in user_prompt
    )

    return user_prompt, needs_multimodal


async def build_ctx_info(
    message: pyrogram.types.Message,
    user: pyrogram.types.User | pyrogram.types.Chat,
    user_data: Any,
    history: list[ModelMessage],
    is_group_chat: bool,
) -> datatype.ContextInfo | None:
    """Build ContextInfo for the current message.

    Returns None if history is non-empty (ctx_info is only sent at the start
    of a conversation).
    """
    if len(history) != 0:
        return None
    if user.id is None:
        return None

    ctx_info = datatype.ContextInfo(
        user_data=datatype.UserData(
            user_id=user.id,
            full_name=user_data.full_name,
            username=user_data.username,
            config={"lang": user_data.user_config.lang}
            if user_data.user_config
            else None,
        ),
        chat_type=message.chat.type.name
        if message.chat and message.chat.type
        else None,
        msg_id=message.id,
        current_time=datetime.now().isoformat(),
        is_group_chat=is_group_chat,
    )
    if is_explicit_reply(message) and message.reply_to_message:
        reply_to = message.reply_to_message
        ctx_info.reply_to_msg_id = reply_to.id
        ctx_info.reply_to_msg_text = reply_to.text or reply_to.caption
    memory = await memttlcache.get(state.memory_key(user.id))
    if memory and isinstance(memory, datatype.ChatMemoryy):
        ctx_info.memory_about_user = memory
    affection_rank = await affection.get_affection_rank(user_data.id)
    append_prompt = get_agent_affection_prompt(affection_rank)
    if append_prompt:
        ctx_info.append_prompt = append_prompt
    if message.guest_query_id:
        ctx_info.append_prompt = (
            (ctx_info.append_prompt or "")
            + "\n[Guest Mode] You are operating in guest mode. "
            "You can only send a single text reply. "
            "You cannot access chat history, send media, stickers, reactions, or polls."
        )
    return ctx_info


def check_needs_multimodal(
    user_prompt: list[UserContent],
    history: list[ModelMessage],
) -> bool:
    """Return True if the user_prompt or any message in history contains
    multimodal content (image, audio, video, document, binary)."""
    if any(isinstance(item, MULTI_MODAL_CONTENT_TYPES) for item in user_prompt):
        return True
    for msg in history:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                content = part.content
                if isinstance(content, list) and any(
                    isinstance(item, MULTI_MODAL_CONTENT_TYPES) for item in content
                ):
                    return True
            elif isinstance(part, ToolReturnPart):
                if part.has_content and isinstance(
                    part.content, MULTI_MODAL_CONTENT_TYPES
                ):
                    return True
    return False
