"""Group-chat message assembly: the markdown user prompt format.

The assembler returns the prompt list: one markdown string followed by the
binary media in image_number order. Transcribe mode replaces the binaries and
back-fills the transcribed attribute by image_number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pyrogram
from pydantic_ai import BinaryContent, UserContent

from kmua import enums
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state

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


def _sender_key(message: pyrogram.types.Message) -> tuple[str, int] | None:
    """Return the stable sender identity used for historical media rules."""
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None:
        sender_id = getattr(sender_chat, "id", None)
        if sender_id is not None:
            return ("chat", sender_id)
    sender = getattr(message, "from_user", None)
    sender_id = getattr(sender, "id", None)
    if sender_id is not None:
        return ("user", sender_id)
    return None


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
        return SenderInfo(name, user_id_str, "Bot", "群员")
    status = "群员"
    if user_id is not None:
        try:
            from kmua.common.tgmethod import get_chat_member

            member = await get_chat_member(client, chat_id, user_id)
            status = _STATUS_NAMES.get(member.status, "群员")
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

    numbered maps message id -> image_number (globally monotonic across the
    conversation: 1 is the oldest image the conversation ever delivered);
    binaries holds the downloads in the same order, so the N-th binary
    corresponds to the N-th fresh image. Messages whose media was already
    delivered (this turn or in an earlier turn) carry a referenced_image_number
    instead of a fresh one — they are tracked in referenced_ids and rendered
    without an image_number attribute.
    """

    numbered: dict[int, int] = field(default_factory=dict)
    binaries: list[BinaryContent] = field(default_factory=list)
    referenced_ids: set[int] = field(default_factory=set)


async def allocate_budget(
    client: pyrogram.client.Client,
    media_messages: list[pyrogram.types.Message],
    current_message_id: int | None,
    initial_seen: dict[str, int] | None = None,
    start_number: int = 1,
) -> Budget:
    """Pick which media messages get their image delivered: newest-first
    selection, deduped by file_unique_id, numbered chronologically. Later
    messages with the same unique image reference the first number.

    ``initial_seen`` carries the unique images already delivered in earlier
    turns of this conversation: those messages are referenced by their old
    number without downloading again. Fresh images number from
    ``start_number`` (the conversation's next free number), so references
    (older numbers) can never collide with them.
    """
    limit = _effective_budget()
    result = Budget()
    if not media_messages:
        return result
    # fresh numbers must always stay above every previously delivered number,
    # whatever the cursor says (defensive: a stale next_number from an old
    # coverage snapshot must never collide with a reference).
    if initial_seen:
        start_number = max(start_number, max(initial_seen.values()) + 1)
    newest_first = sorted(
        media_messages,
        key=lambda m: (m.id or 0, m.id == current_message_id),
        reverse=True,
    )
    seen_unique: dict[str, int] = dict(initial_seen or {})
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
    next_number = start_number
    for msg in winners:
        data = await _download(client, msg)
        if data is None:
            continue
        unique = file_unique_id_of(msg)
        number = next_number
        next_number += 1
        result.numbered[msg.id] = number
        result.binaries.append(data)
        if unique is not None:
            seen_unique[unique] = number
    for msg in references:
        unique = file_unique_id_of(msg)
        number = seen_unique.get(unique) if unique else None
        if number:
            result.numbered[msg.id] = number
            result.referenced_ids.add(msg.id)
    return result


def _budget_media_meta(
    media_messages: list[pyrogram.types.Message], budget: Budget
) -> dict[str, int]:
    """file_unique_id -> image_number for every image freshly delivered this
    turn (references to already-seen media are excluded: they carry old
    numbers that must not advance the cursor)."""
    meta: dict[str, int] = {}
    for msg in media_messages:
        if msg.id not in budget.numbered or msg.id in budget.referenced_ids:
            continue
        unique = file_unique_id_of(msg)
        if unique is None:
            continue
        meta[unique] = budget.numbered[msg.id]
    return meta


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


def _env_header(
    message: pyrogram.types.Message, ctx: datatype.ContextInfo | None
) -> str:
    """Per-prompt environment stamp: chat title and current time. The chat
    info and the ContextInfo fields the per-turn message blocks do not
    already show (user profile, memory about the user, affection prompt)
    are included only on the first prompt (ctx present)."""
    chat = message.chat
    title = getattr(chat, "title", None) or "未知群组"
    lines = [f"# 群聊 - {title}", f"当前时间: {_now_text()}"]
    if ctx is None:
        return "\n".join(lines)
    info_lines = _chat_info_lines(chat)
    if info_lines:
        lines.append("群组信息:")
        lines.extend(f"  {line}" for line in info_lines)
    if ctx.memory_about_user is not None:
        memory_text = ctx.memory_about_user.to_text(is_group_chat=ctx.is_group_chat)
        if memory_text:
            lines.append(f"关于用户的记忆: ({memory_text})")
    if ctx.append_prompt:
        lines.append(f"附加提示: {ctx.append_prompt}")
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
    referenced: bool = False,
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
        if referenced:
            # already delivered in an earlier turn (or earlier in this one):
            # the model saw it verbatim, so reference the number, never resend
            attrs.append(f"referenced_media={image_number}")
        else:
            attrs.append(f"image_number={image_number}")
    if unprocessed:
        attrs.append(f"unprocessed={_quote(unprocessed)}")
    if message.service is not None:
        # join/leave/pin/title change: no text or caption, describe the event
        text = _service_text(message)
    else:
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
            _msg_line(
                msg,
                budget.numbered.get(msg.id),
                _unprocessed_reason(msg),
                referenced=msg.id in budget.referenced_ids,
            )
        )
    return "\n".join(lines)


class _ReplyChainLink:
    """One hop of the reply chain the depth walker traverses.

    Carries exactly the four fields the walk reads, wrapping a real
    pyrogram Message when the runtime fetched that ancestor and a stub
    otherwise (an unknown ancestor ends the walk).
    """

    __slots__ = (
        "id",
        "reply_to_message_id",
        "reply_to_top_message_id",
        "reply_to_message",
    )

    def __init__(
        self,
        id: int,
        reply_to_message_id: int | None,
        reply_to_top_message_id: int | None,
        reply_to_message: pyrogram.types.Message | None = None,
    ) -> None:
        self.id = id
        self.reply_to_message_id = reply_to_message_id
        self.reply_to_top_message_id = reply_to_top_message_id
        self.reply_to_message = reply_to_message


def _reply_chain_depth(message: pyrogram.types.Message) -> int:
    """How many reply hops the current message sits on (1 = direct reply)."""
    depth = 0
    current: _ReplyChainLink = _ReplyChainLink(
        id=message.id,
        reply_to_message_id=message.reply_to_message_id,
        reply_to_top_message_id=message.reply_to_top_message_id,
        reply_to_message=message.reply_to_message,
    )
    seen: set[int] = {current.id}
    while depth < 50:
        reply_id = current.reply_to_message_id
        if (
            not reply_id
            or reply_id in seen
            or reply_id == current.reply_to_top_message_id
        ):
            break
        depth += 1
        seen.add(reply_id)
        resolved = current.reply_to_message
        if (
            resolved is not None
            and not getattr(resolved, "empty", False)
            and resolved.id == reply_id
        ):
            # Keep walking through the resolved ancestor: its own reply link
            # continues the chain.
            current = _ReplyChainLink(
                id=resolved.id,
                reply_to_message_id=resolved.reply_to_message_id,
                reply_to_top_message_id=resolved.reply_to_top_message_id,
                reply_to_message=resolved.reply_to_message,
            )
        else:
            # The ancestor object is unknown (Telegram did not attach it);
            # end the walk at this hop.
            current = _ReplyChainLink(
                id=reply_id,
                reply_to_message_id=None,
                reply_to_top_message_id=current.reply_to_top_message_id,
            )
    return depth


def _is_deleted_message(message: pyrogram.types.Message | None) -> bool:
    """Return whether Telegram supplied an empty/deleted message shell."""
    return message is None or bool(getattr(message, "empty", False))


async def build_group_prompt(
    client: pyrogram.client.Client,
    message: pyrogram.types.Message,
    nearby: list[pyrogram.types.Message],
    ctx: datatype.ContextInfo | None,
    coverage: state.PromptCoverage | None = None,
) -> tuple[list[UserContent], dict[str, int]]:
    """Assemble the group-chat markdown user prompt.

    Returns (prompt list, media meta): the markdown string followed by any
    binary media in image_number order, plus file_unique_id -> image_number of
    every image this turn delivered (for the conversation coverage cursor).
    Nearby messages already delivered in a previous turn of the same
    conversation (id <= coverage.last_message_id) are omitted entirely: they
    live verbatim in the model history, so resending them would only duplicate
    tokens and re-download media.
    Only historical media from the current sender, except stickers, enters the
    media budget; the current message and its direct reply remain unrestricted.
    The env header (chat name, current time) goes into every prompt; ContextInfo
    extras (chat info, user profile, memory, affection prompt) only on the first
    prompt (ctx present).
    """
    chat = message.chat
    chat_id = chat.id if chat is not None and chat.id is not None else 0
    covered_until = coverage.last_message_id if coverage else 0
    initial_seen = coverage.sent_media if coverage else None

    # one-level reply target; deeper chains surface as reply_chain_depth
    reply_msg = None
    if is_explicit_reply(message) and message.reply_to_message:
        candidate = message.reply_to_message
        if not _is_deleted_message(candidate):
            reply_msg = candidate
    reply_id = reply_msg.id if reply_msg is not None else None

    seen: set[int] = {message.id}
    history: list[pyrogram.types.Message] = []
    for prev in nearby:
        if _is_deleted_message(prev) or prev.id in seen or prev.id == reply_id:
            continue
        seen.add(prev.id)
        if prev.id > covered_until:
            history.append(prev)

    if reply_msg is not None:
        seen.add(reply_msg.id)

    senders: dict[int, SenderInfo] = {}
    for msg in [*history, reply_msg, message]:
        if msg is None or msg.id in senders:
            continue
        senders[msg.id] = await resolve_sender(client, chat_id, msg)

    current_sender = _sender_key(message)

    def historical_media_allowed(msg: pyrogram.types.Message) -> bool:
        if msg.media is pyrogram.enums.MessageMediaType.STICKER:
            return False
        return current_sender is not None and _sender_key(msg) == current_sender

    def keep_media(msg: pyrogram.types.Message) -> bool:
        # The current message and its direct reply are always eligible; the
        # budget and file_unique_id deduplication still apply to both.
        if msg is message or msg is reply_msg:
            return True
        # Historical media from any other sender, including stickers, is
        # rendered as metadata only and never enters the media budget.
        return historical_media_allowed(msg)

    media_messages = [
        m
        for m in (*history, reply_msg, message)
        if m is not None and m.media and keep_media(m)
    ]
    budget = await allocate_budget(
        client,
        media_messages,
        message.id,
        initial_seen=initial_seen,
        start_number=coverage.next_number if coverage else 1,
    )

    parts: list[str] = [_env_header(message, ctx)]

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
        if message.id in budget.referenced_ids:
            current_lines.append(
                f"消息图号: 图{budget.numbered[message.id]} (此图已在之前的对话中展示)"
            )
        else:
            current_lines.append(f"消息图号: 图{budget.numbered[message.id]}")
    current_lines.append(f"消息 ID: {message.id}")
    depth = _reply_chain_depth(message)
    if depth > 1:
        current_lines.append(
            f"reply_chain_depth={depth} (可用 chat://history?reply_chain_of={message.id} 获取该消息的完整回复链)"
        )
    if reply_msg is not None:
        reply_sender = senders.get(reply_msg.id)
        reply_label = reply_sender.label() if reply_sender else "?"
        reply_text = reply_msg.text or reply_msg.caption or ""
        current_lines.append("当前用户所回复的消息:")
        current_lines.append(f"    发送者: {reply_label}")
        current_lines.append(f"    消息内容: {_quote(reply_text)}")
        if reply_msg.id in budget.numbered:
            if reply_msg.id in budget.referenced_ids:
                current_lines.append(
                    f"    消息图号: 图{budget.numbered[reply_msg.id]} (此图已在之前的对话中展示)"
                )
            else:
                current_lines.append(f"    消息图号: 图{budget.numbered[reply_msg.id]}")
        current_lines.append(f"    消息 ID: {reply_msg.id}")
    parts.append("\n".join(current_lines))

    markdown = "\n\n".join(parts)
    meta = _budget_media_meta(media_messages, budget)
    return [markdown, *budget.binaries], meta


# An image_number= attribute (not referenced_media=): negative lookbehind so
# the dedicated reference attribute never matches.
_IMAGE_NUMBER_RE = re.compile(r"(?<![A-Za-z_])image_number=\d+ ")


def apply_transcriptions(
    prompt: list[UserContent], transcriptions: list[str]
) -> list[UserContent]:
    """Transcribe-mode post-processing: the runner replaced each binary with
    its transcription text in order; fold the texts back into the markdown as
    the transcribed attribute of the matching image_number.

    Numbers are globally monotonic across the conversation, so match by
    occurrence order instead of the number value. Reference attributes
    (referenced_media=) are not image_number attributes and are skipped.
    """
    if not prompt or not isinstance(prompt[0], str) or not transcriptions:
        return prompt
    markdown = prompt[0]
    matches = list(_IMAGE_NUMBER_RE.finditer(markdown))
    if not matches:
        return prompt
    # insert from the back so earlier match positions stay valid
    for idx in range(len(transcriptions) - 1, -1, -1):
        offset = idx + 1
        if offset > len(matches):
            continue
        match = matches[offset - 1]
        insert_at = match.end()
        markdown = (
            markdown[:insert_at]
            + f"transcribed={_quote(transcriptions[idx])} "
            + markdown[insert_at:]
        )
    return [markdown, *prompt[1:]]
