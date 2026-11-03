"""Telegram user profiles for ``user://`` read targets.

Reads are scoped to the current chat: in a group only its members, in a
private chat only the current user. ``?include=`` optionally adds affection,
memory, coins, marriage, activity stats and account data.
"""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic_ai import RunContext
from pyrogram.enums import ChatMemberStatus, ChatType

from kmua import affection, common, database
from kmua.config import app_config

from ... import state
from .. import datatype
from .media import MediaPayload

_CURRENT_USER_ALIAS = "current"
_RESERVED_USER_NAMES = {"me", "self", "empty"}
_EXTENDED_FIELDS = (
    "affection",
    "memory",
    "coins",
    "marriage",
    "stats",
    "account",
)


def _profile_photo(chat: Any) -> Any | None:
    """The photo Telegram would show for this user, if any."""
    return (
        getattr(chat, "personal_photo", None)
        or getattr(chat, "photo", None)
        or getattr(chat, "public_photo", None)
    )


def _profile_data(chat: Any) -> dict[str, Any]:
    photo = _profile_photo(chat)
    data: dict[str, Any] = {
        "id": chat.id,
        "is_bot": chat.type == ChatType.BOT,
        "has_photo": photo is not None,
    }
    for key in ("first_name", "last_name", "full_name", "username", "bio"):
        value = getattr(chat, key, None)
        if value is not None:
            data[key] = value
    if photo is not None:
        data["avatar"] = f"user://{chat.id}/avatar"
    return data


def _user_target(rest: str, current_id: int) -> tuple[int | str, bool]:
    """Resolve a ``user://`` path to a user reference and avatar flag."""
    parts = [part for part in rest.split("/") if part]
    avatar = len(parts) > 1 and parts[-1] in ("avatar", "photo")
    if avatar:
        parts.pop()
    if not parts:
        raise ValueError(
            "Missing user:// target; use user://current or user://<user_id>."
        )
    if len(parts) != 1:
        raise ValueError(
            f"Invalid user:// target {rest!r}; use user://<user_id>[/avatar]."
        )
    token = parts[0]
    if token.lower() == _CURRENT_USER_ALIAS:
        target: int | str = current_id
    elif token.lstrip("-").isdigit():
        target = int(token)
        if target <= 0:
            raise ValueError("user:// target must be a user id, not a chat id.")
    else:
        username = token.removeprefix("@")
        if not username or token.startswith("+") or username.isdigit():
            raise ValueError("user:// target must be a numeric user id or a @username.")
        if username.lower() in _RESERVED_USER_NAMES:
            raise ValueError(f"user://{username} is not a target; use user://current.")
        target = token
    return target, avatar


def _user_query(rest: str) -> tuple[str, tuple[str, ...]]:
    """Split a ``user://`` path into its target path and requested extras."""
    parts = urlsplit(rest)
    query = parse_qs(parts.query)
    unknown = set(query) - {"include"}
    if unknown:
        raise ValueError(
            f"Unknown user:// query parameter(s): {', '.join(sorted(unknown))}; "
            f"supported: include={','.join(_EXTENDED_FIELDS)} (or include=all)."
        )
    requested: set[str] = set()
    for value in query.get("include", []):
        for item in value.split(","):
            field = item.strip().lower()
            if not field:
                continue
            if field == "all":
                requested.update(_EXTENDED_FIELDS)
            elif field in _EXTENDED_FIELDS:
                requested.add(field)
            else:
                raise ValueError(
                    f"Unknown user:// include field {field!r}; supported: "
                    f"{', '.join(_EXTENDED_FIELDS)}, all."
                )
    return parts.path, tuple(field for field in _EXTENDED_FIELDS if field in requested)


def _memory_data(memory: datatype.ChatMemoryy) -> dict[str, Any]:
    """Memory fields that actually contain something."""
    data: dict[str, Any] = {}
    for key, value in memory.model_dump(exclude_none=True).items():
        if isinstance(value, list):
            value = [item for item in value if item]
        if value not in ("", [], {}):
            data[key] = value
    return data


async def _extended_profile(user_id: int, fields: tuple[str, ...]) -> dict[str, Any]:
    """Persistent user state that the basic Telegram profile does not carry."""
    user_data = await database.get_user_by_id(user_id) if fields else None
    data: dict[str, Any] = {}
    if "affection" in fields:
        if user_data is None:
            data["affection"] = None
        else:
            value = await affection.get_user_affection(user_id)
            rank = await database.get_affection_percentile(value)
            data["affection"] = {"value": value, "rank": round(rank, 4)}
    if "memory" in fields:
        memory = await common.memttlcache.get(state.memory_key(user_id))
        data["memory"] = (
            _memory_data(memory) if isinstance(memory, datatype.ChatMemoryy) else None
        )
    if "coins" in fields:
        data["coins"] = user_data.user_config.coins if user_data is not None else None
    if "marriage" in fields:
        if user_data is None:
            data["marriage"] = None
        else:
            partner_id = user_data.married_waifu_id
            partner_name = None
            if partner_id is not None:
                partner = await database.get_user_by_id(partner_id)
                partner_name = partner.full_name if partner is not None else None
            data["marriage"] = {
                "is_married": user_data.is_married,
                "partner_id": partner_id,
                "partner_name": partner_name,
                "waifu_mention": user_data.waifu_mention,
            }
    if "stats" in fields:
        if user_data is None:
            data["stats"] = None
        else:
            quotes = await database.get_user_quote_count(user_id)
            gifts = await database.count_user_gifts(user_id)
            chats = await database.get_user_chats(user_id)
            data["stats"] = {
                "quote_count": quotes,
                "gift_count": gifts,
                "chat_count": len(chats),
            }
    if "account" in fields:
        if user_data is None:
            data["account"] = None
        else:
            config = user_data.user_config
            data["account"] = {
                "lang": config.lang,
                "is_real_user": user_data.is_real_user,
                "is_blocked": user_data.is_blocked,
                "created_at": (
                    user_data.created_at.isoformat()
                    if user_data.created_at is not None
                    else None
                ),
            }
    return data


async def _load_user(ctx: RunContext[datatype.ContextDeps], target: int | str) -> Any:
    try:
        chat = await ctx.deps.client.get_chat(target)
    except Exception as e:
        raise ValueError(
            f"Cannot read the profile of {target!r}: {e.__class__.__name__}."
        ) from e
    if chat is None:
        raise ValueError(f"No profile found for {target!r}.")
    if chat.type not in (ChatType.PRIVATE, ChatType.BOT):
        raise ValueError(f"{target!r} is not a user profile.")
    return chat


async def _ensure_target_scope(
    ctx: RunContext[datatype.ContextDeps], target: int | str
) -> None:
    """Reject targets outside the current chat before loading their profile."""
    if ctx.deps.chat_id == ctx.deps.user_id:
        if isinstance(target, int) and target != ctx.deps.user_id:
            raise ValueError(
                "In a private chat only the current user's profile is readable."
            )
        return
    try:
        member = await common.get_chat_member(ctx.deps.client, ctx.deps.chat_id, target)
    except Exception as e:
        raise ValueError(f"User {target} is not a member of this group.") from e
    if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        raise ValueError(f"User {target} is not a member of this group.")


def _ensure_resolved_scope(ctx: RunContext[datatype.ContextDeps], chat: Any) -> None:
    """Verify that a private-chat username resolved to the current user."""
    if ctx.deps.chat_id == ctx.deps.user_id and chat.id != ctx.deps.user_id:
        raise ValueError(
            "In a private chat only the current user's profile is readable."
        )


async def _download_avatar(
    ctx: RunContext[datatype.ContextDeps], file_id: str, label: str
) -> bytes:
    timeout = app_config.agent_download_timeout or None
    try:
        media = await asyncio.wait_for(
            ctx.deps.client.download_media(file_id, in_memory=True),
            timeout=timeout,
        )
    except TimeoutError as e:
        raise ValueError(f"{label}: download timed out.") from e
    if not isinstance(media, BytesIO):
        raise ValueError(f"Failed to download {label}.")
    data = media.getvalue()
    max_bytes = app_config.agent_download_max_bytes
    if len(data) > max_bytes:
        raise ValueError(f"{label}: file is over the {max_bytes} byte limit.")
    return data


async def _read_user(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> str | MediaPayload:
    path, include = _user_query(rest)
    target, want_avatar = _user_target(path, ctx.deps.user_id)
    if want_avatar and include:
        raise ValueError(
            "include is only available for profile metadata; call the target "
            "without /avatar for extras, or read /avatar separately."
        )
    await _ensure_target_scope(ctx, target)
    chat = await _load_user(ctx, target)
    _ensure_resolved_scope(ctx, chat)
    if not want_avatar:
        data = _profile_data(chat)
        if include:
            data.update(await _extended_profile(chat.id, include))
        return json.dumps(data, ensure_ascii=False, indent=2)

    photo = _profile_photo(chat)
    if photo is None:
        return f"User {chat.id} has no profile photo."
    label = f"profile photo of user {chat.id}"
    return MediaPayload(
        data=await _download_avatar(ctx, photo.big_file_id, label),
        media_type="image/jpeg",
        label=label,
    )


__all__ = ["_read_user"]
