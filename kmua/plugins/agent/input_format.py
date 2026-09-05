"""Group-chat message assembly: the markdown user prompt format.

The assembler returns the prompt list: one markdown string followed by the
binary media in image_number order. Transcribe mode replaces the binaries and
back-fills the transcribed attribute by image_number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pyrogram
from pydantic_ai import BinaryContent, UserContent

from kmua import enums
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype

# Media types deliverable to the model, with size caps and the multimodal-inputs key.
_SIZE_CAPS = {
    pyrogram.enums.MessageMediaType.VIDEO: 20 * 1024 * 1024,
    pyrogram.enums.MessageMediaType.AUDIO: 10 * 1024 * 1024,
    pyrogram.enums.MessageMediaType.VOICE: 10 * 1024 * 1024,
    pyrogram.enums.MessageMediaType.DOCUMENT: 10 * 1024 * 1024,
}

_INPUTS_KEY = {
    pyrogram.enums.MessageMediaType.VIDEO: "video",
    pyrogram.enums.MessageMediaType.AUDIO: "audio",
    pyrogram.enums.MessageMediaType.VOICE: "audio",
}

_MEDIA_TYPE_NAMES = {
    pyrogram.enums.MessageMediaType.PHOTO: "photo",
    pyrogram.enums.MessageMediaType.VIDEO: "video",
    pyrogram.enums.MessageMediaType.AUDIO: "audio",
    pyrogram.enums.MessageMediaType.VOICE: "voice",
    pyrogram.enums.MessageMediaType.DOCUMENT: "document",
    pyrogram.enums.MessageMediaType.STICKER: "sticker",
    pyrogram.enums.MessageMediaType.VIDEO_NOTE: "video_note",
    pyrogram.enums.MessageMediaType.ANIMATION: "animation",
    pyrogram.enums.MessageMediaType.LIVE_PHOTO: "live_photo",
}


def media_type_name(
    media: pyrogram.enums.MessageMediaType | None,
) -> str:
    """Lowercase media_type attribute value; empty when there is no media."""
    if media is None:
        return ""
    return _MEDIA_TYPE_NAMES.get(media, str(media).rsplit(".", 1)[-1].lower())


def file_unique_id_of(message: pyrogram.types.Message) -> str | None:
    """The unique id of a message's media payload, used to dedupe identical
    images across senders."""
    media = message.media
    if media is None:
        return None
    payload = getattr(message, media.name.lower() if media.name else "", None)
    if payload is None:
        for attr in (
            "photo",
            "video",
            "audio",
            "voice",
            "document",
            "sticker",
            "animation",
            "video_note",
        ):
            payload = getattr(message, attr, None)
            if payload is not None:
                break
    unique = getattr(payload, "file_unique_id", None)
    return unique or None


def is_deliverable(
    message: pyrogram.types.Message,
) -> bool:
    """Whether the message's media can be downloaded and sent to the model
    (type enabled in agent_multimodal_inputs, size within cap, not a known
    unsupported kind)."""
    media = message.media
    if media is None or not app_config.agent_multimodal:
        return False
    if media in (
        pyrogram.enums.MessageMediaType.POLL,
        pyrogram.enums.MessageMediaType.WEB_PAGE,
    ):
        # Text-represented; never a binary.
        return False
    if media is pyrogram.enums.MessageMediaType.PHOTO:
        return "photo" in app_config.agent_multimodal_inputs and bool(
            message.photo and message.photo.file_id
        )
    if media is pyrogram.enums.MessageMediaType.STICKER:
        sticker = message.sticker
        if not sticker or sticker.is_animated:
            return False
        return "photo" in app_config.agent_multimodal_inputs and bool(sticker.file_id)
    cap = _SIZE_CAPS.get(media)
    if cap is None:
        return False
    payload = getattr(message, media.name.lower(), None) if media.name else None
    if payload is None or not getattr(payload, "file_id", None):
        return False
    size = getattr(payload, "file_size", None)
    if size is not None and size > cap:
        return False
    key = _INPUTS_KEY.get(media)
    return key is not None and key in app_config.agent_multimodal_inputs


def deliverable_file_id(message: pyrogram.types.Message) -> str | None:
    """The file_id to download when the message's media is deliverable."""
    if not is_deliverable(message):
        return None
    media = message.media
    if media is None:
        return None
    if media is pyrogram.enums.MessageMediaType.STICKER:
        return message.sticker.file_id if message.sticker else None
    payload = getattr(message, media.name.lower(), None) if media.name else None
    return getattr(payload, "file_id", None)


@dataclass
class SenderInfo:
    name: str
    user_id: str
    kind: str  # 真人 / 频道 / bot / 匿名管理 / 系统
    status: str  # 群主 / 管理员 / 普通群员 / 系统

    def label(self) -> str:
        return f"{self.name}({self.user_id}) | {self.kind} | {self.status}"


_STATUS_NAMES = {
    pyrogram.enums.ChatMemberStatus.OWNER: "群主",
    pyrogram.enums.ChatMemberStatus.ADMINISTRATOR: "管理员",
}


async def resolve_sender(
    client: pyrogram.client.Client,
    chat_id: int,
    message: pyrogram.types.Message,
) -> SenderInfo:
    """Sender identity for the header line, with a TTL-cached member status."""
    sender = message.sender_chat or message.from_user
    if sender is None:
        # Service message (join/leave/pin): no sender at all.
        return SenderInfo("系统", "系统", "系统", "系统")
    name = (
        getattr(sender, "first_name", None) or getattr(sender, "title", None) or "未知"
    )
    user_id = getattr(sender, "id", None)
    user_id_str = str(user_id) if user_id is not None else "?"
    if message.sender_chat is not None:
        # Anonymous admins and channel posts both travel with sender_chat set;
        # a sender_chat equal to the group itself is an anonymous admin.
        if message.sender_chat.id != chat_id:
            return SenderInfo(name, user_id_str, "频道", "频道")
        from_user = message.from_user
        if from_user is not None and from_user.id == enums.ChatID.ANONYMOUS_ADMIN:
            return SenderInfo(name, user_id_str, "匿名管理", "管理员")
        return SenderInfo(name, user_id_str, "匿名管理", "管理员")
    if getattr(message.from_user, "is_bot", False):
        return SenderInfo(name, user_id_str, "bot", "普通群员")
    status = "普通群员"
    if user_id is not None:
        try:
            from kmua.common.tgmethod import get_chat_member

            member = await get_chat_member(client, chat_id, user_id)
            status = _STATUS_NAMES.get(member.status, "普通群员")
        except Exception as e:
            logger.debug(
                f"member status lookup failed for {user_id} in {chat_id}: "
                f"{e.__class__.__name__}"
            )
    return SenderInfo(name, user_id_str, "真人", status)


def _quote(value: str) -> str:
    """Attribute value: double-quoted, newlines kept, inner quotes escaped."""
    return '"' + value.replace('"', '\\"') + '"'


@dataclass
class Budget:
    """Allocated image numbering over the assembled messages.

    numbered maps message id -> 1-based image_number (chronological: 1 is the
    oldest winner); binaries holds the downloads in the same order, so the
    N-th binary corresponds to image_number N. Messages carrying an already-sent
    unique image reference its number without a new binary.
    """

    numbered: dict[int, int] = field(default_factory=dict)
    binaries: list[BinaryContent] = field(default_factory=list)


async def allocate_budget(
    client: pyrogram.client.Client,
    media_messages: list[pyrogram.types.Message],
    current_message_id: int | None,
) -> Budget:
    """Pick which media messages get their image delivered: newest-first
    selection, deduped by file_unique_id, numbered chronologically. Later
    messages with the same unique image reference the first number."""
    limit = _effective_budget()
    result = Budget()
    if not media_messages:
        return result
    newest_first = sorted(
        media_messages,
        key=lambda m: (m.id or 0, m.id == current_message_id),
        reverse=True,
    )
    seen_unique: dict[str, int] = {}
    winners: list[pyrogram.types.Message] = []
    references: list[pyrogram.types.Message] = []
    for msg in newest_first:
        unique = file_unique_id_of(msg)
        if unique is not None and unique in seen_unique:
            # same image already budgeted: mark for number reference only
            references.append(msg)
            continue
        if len(winners) >= limit:
            break
        if deliverable_file_id(msg) is None:
            continue
        if unique is not None:
            seen_unique[unique] = 0  # number assigned after chronological sort
        winners.append(msg)
    # chronological numbering: 1 = oldest winner; current message last
    winners.sort(key=lambda m: (m.id or 0, m.id == current_message_id))
    for msg in winners:
        data = await _download(client, msg)
        if data is None:
            continue
        unique = file_unique_id_of(msg)
        number = len(result.binaries) + 1
        result.numbered[msg.id] = number
        result.binaries.append(data)
        if unique is not None:
            seen_unique[unique] = number
    for msg in references:
        unique = file_unique_id_of(msg)
        number = seen_unique.get(unique) if unique else None
        if number:
            result.numbered[msg.id] = number
    return result


def _effective_budget() -> int:
    """Per-turn image budget; a huge number stands in for 'unlimited'."""
    per_turn = app_config.agent_multimodal_input_count
    global_cap = app_config.agent_multimodal_max_items
    if per_turn == 0 and global_cap == 0:
        return 10**9
    if per_turn == 0:
        return global_cap
    if global_cap == 0:
        return per_turn
    return min(per_turn, global_cap)


async def _download(
    client: pyrogram.client.Client, message: pyrogram.types.Message
) -> BinaryContent | None:
    """Download the message's media with the correct media_type for its kind.

    Video stickers carry no raster image: their first frame is extracted with
    ffmpeg and delivered as WebP, like the legacy path.
    """
    from .prompt import _download_media_with_timeout

    media = message.media
    file_id = deliverable_file_id(message)
    if media is None or file_id is None:
        return None
    data = await _download_media_with_timeout(client, file_id)
    if data is None:
        return None
    payload = getattr(message, media.name.lower(), None) if media.name else None
    if media is pyrogram.enums.MessageMediaType.PHOTO:
        return BinaryContent(data=data.getvalue(), media_type="image/jpeg")
    if media is pyrogram.enums.MessageMediaType.STICKER:
        sticker = message.sticker
        if sticker is not None and sticker.is_video:
            from kmua.common.utils import webm_first_frame

            frame = await webm_first_frame(data.getvalue())
            if frame is None:
                return None
            return BinaryContent(data=frame, media_type="image/webp")
        return BinaryContent(data=data.getvalue(), media_type="image/webp")
    media_type = getattr(payload, "mime_type", None) or "application/octet-stream"
    return BinaryContent(data=data.getvalue(), media_type=media_type)


def _service_text(message: pyrogram.types.Message) -> str:
    """Readable text for a service message (join/leave/title change/...)."""
    service = message.service
    actor = ""
    if message.from_user is not None:
        actor = getattr(message.from_user, "first_name", None) or ""
    target = ""
    if service is not None and message.service is not None:
        new_member = getattr(message, "new_chat_members", None)
        left = getattr(message, "left_chat_member", None)
        if new_member:
            target = ", ".join(getattr(u, "first_name", None) or "" for u in new_member)
        elif left is not None:
            target = getattr(left, "first_name", None) or ""
    kind = str(service).rsplit(".", 1)[-1] if service is not None else "SERVICE"
    parts = [p for p in (kind, actor, target) if p]
    return " ".join(parts) if parts else "系统消息"


def _unprocessed_reason(message: pyrogram.types.Message) -> str | None:
    """Why this media cannot be delivered even in principle (not budget)."""
    if message.media is None:
        return None
    if is_deliverable(message):
        return None
    return "无法查看此内容"


def _env_header(message: pyrogram.types.Message, ctx: datatype.ContextInfo) -> str:
    """First-prompt environment block: chat title, time, chat info and the
    ContextInfo content (memory, affection prompts, guest notice)."""
    chat = message.chat
    title = getattr(chat, "title", None) or "未知群组"
    lines = [f"# 群聊 - {title}", f"当前时间: {_now_text()}"]
    info_lines = _chat_info_lines(chat)
    if info_lines:
        lines.append("群组信息:")
        lines.extend(f"  {line}" for line in info_lines)
    ctx_lines = [
        line
        for line in ctx.to_text().splitlines()
        if line and not line.startswith("ContextInfo[")
    ]
    if ctx_lines:
        lines.extend(ctx_lines)
    return "\n".join(lines)


def _now_text() -> str:

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _chat_info_lines(chat: pyrogram.types.Chat | None) -> list[str]:
    if chat is None:
        return []
    fields: list[tuple[str, Any]] = []
    if chat.id is not None:
        fields.append(("群 ID", chat.id))
    if getattr(chat, "username", None):
        fields.append(("用户名", f"@{chat.username}"))
    if getattr(chat, "description", None):
        fields.append(("简介", chat.description))
    member_count = getattr(chat, "members_count", None)
    if member_count:
        fields.append(("成员数", member_count))
    return [f"{name}: {value}" for name, value in fields]


def _msg_line(
    message: pyrogram.types.Message,
    image_number: int | None,
    unprocessed: str | None,
) -> str:
    attrs = [f"id={message.id}"]
    if message.date:
        attrs.append(f"date={_quote(message.date.strftime('%Y-%m-%d %H:%M:%S'))}")
    if (
        message.reply_to_message_id
        and message.reply_to_top_message_id != message.reply_to_message_id
    ):
        attrs.append(f"reply_to_message_id={message.reply_to_message_id}")
    media = message.media
    type_name = media_type_name(media)
    if type_name:
        attrs.append(f"media_type={_quote(type_name)}")
    if image_number is not None:
        attrs.append(f"image_number={image_number}")
    if unprocessed:
        attrs.append(f"unprocessed={_quote(unprocessed)}")
    text = message.text or message.caption or ""
    attrs.append(f"text={_quote(text)}")
    return f"    - <msg {' '.join(attrs)}>"


def _render_history(
    messages: list[pyrogram.types.Message],
    senders: dict[int, SenderInfo],
    budget: Budget,
) -> str:
    """The 历史消息 section: chronological, consecutive-sender grouping."""
    lines: list[str] = []
    current_label: str | None = None
    for msg in messages:
        sender = senders.get(msg.id)
        label = sender.label() if sender else "?"
        if label != current_label:
            lines.append(f"{label}:")
            current_label = label
        lines.append(
            _msg_line(msg, budget.numbered.get(msg.id), _unprocessed_reason(msg))
        )
    return "\n".join(lines)


def _reply_chain_depth(message: pyrogram.types.Message) -> int:
    """How many reply hops the current message sits on (1 = direct reply)."""
    depth = 0
    current = message
    while depth < 50:
        reply_id = current.reply_to_message_id
        if not reply_id or reply_id == current.reply_to_top_message_id:
            break
        depth += 1
        current = SimpleNamespace(
            reply_to_message_id=reply_id, reply_to_top_message_id=None
        )  # type: ignore[arg-type]
    return depth


async def build_group_prompt(
    client: pyrogram.client.Client,
    message: pyrogram.types.Message,
    nearby: list[pyrogram.types.Message],
    ctx: datatype.ContextInfo | None,
) -> list[UserContent]:
    """Assemble the group-chat markdown user prompt.

    Returns the prompt list: the markdown string followed by any binary media
    in image_number order. The env header (chat name, time, chat info and the
    ContextInfo content) appears only when ctx is present — i.e. the first
    prompt of a conversation.
    """
    chat = message.chat
    chat_id = chat.id if chat is not None and chat.id is not None else 0

    # one-level reply target; deeper chains surface as reply_chain_depth
    reply_msg = None
    if is_explicit_reply(message) and message.reply_to_message:
        reply_msg = message.reply_to_message

    seen: set[int] = {message.id}
    history: list[pyrogram.types.Message] = []
    for prev in nearby:
        if prev.id in seen:
            continue
        seen.add(prev.id)
        history.append(prev)

    if reply_msg is not None and reply_msg.id not in seen:
        seen.add(reply_msg.id)

    senders: dict[int, SenderInfo] = {}
    for msg in [*history, reply_msg, message]:
        if msg is None or msg.id in senders:
            continue
        senders[msg.id] = await resolve_sender(client, chat_id, msg)

    media_messages = [
        m for m in (*history, reply_msg, message) if m is not None and m.media
    ]
    budget = await allocate_budget(client, media_messages, message.id)

    parts: list[str] = []
    if ctx is not None:
        parts.append(_env_header(message, ctx))

    if history:
        parts.append("## 历史消息\n")
        parts.append(_render_history(history, senders, budget))

    parts.append("## 当前消息\n")
    sender = senders.get(message.id)
    sender_label = sender.label() if sender else "?"
    current_lines = [f"当前用户: {sender_label}"]
    current_text = message.text or message.caption or ""
    current_lines.append(f"消息内容: {_quote(current_text)}")
    if message.id in budget.numbered:
        current_lines.append(f"消息图号: 图{budget.numbered[message.id]}")
    current_lines.append(f"消息 ID: {message.id}")
    depth = _reply_chain_depth(message)
    if depth > 1:
        current_lines.append(
            f"reply_chain_depth={depth} (可用 chat://history?from_id=<id>&to_id=<id> 获取链上更早的消息)"
        )
    if reply_msg is not None:
        reply_sender = senders.get(reply_msg.id)
        reply_label = reply_sender.label() if reply_sender else "?"
        reply_text = reply_msg.text or reply_msg.caption or ""
        current_lines.append("当前用户所回复的消息:")
        current_lines.append(f"    发送者: {reply_label}")
        current_lines.append(f"    消息内容: {_quote(reply_text)}")
        if reply_msg.id in budget.numbered:
            current_lines.append(f"    消息图号: 图{budget.numbered[reply_msg.id]}")
        current_lines.append(f"    消息 ID: {reply_msg.id}")
    parts.append("\n".join(current_lines))

    markdown = "\n\n".join(parts)
    return [markdown, *budget.binaries]


def apply_transcriptions(
    prompt: list[UserContent], transcriptions: list[str]
) -> list[UserContent]:
    """Transcribe-mode post-processing: the runner replaced each binary with
    its transcription text in order; fold the texts back into the markdown as
    the transcribed attribute of the matching image_number."""
    if not prompt or not isinstance(prompt[0], str) or not transcriptions:
        return prompt
    markdown = prompt[0]
    for offset, transcription in enumerate(transcriptions, start=1):
        marker = f"image_number={offset} "
        idx = markdown.find(marker)
        if idx < 0:
            continue
        # insert transcribed="..." right after the image_number attr
        insert_at = idx + len(marker)
        markdown = (
            markdown[:insert_at]
            + f"transcribed={_quote(transcription)} "
            + markdown[insert_at:]
        )
    return [markdown, *prompt[1:]]
