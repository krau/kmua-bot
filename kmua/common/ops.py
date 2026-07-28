"""Operations shared by the bot commands and the Mini App API.

Each function here was originally inline inside a plugin handler. The handlers now
delegate to these, so the panel and the chat commands cannot drift apart: one
implementation, two entry points, and any rule change lands in both at once.

Nothing in this module talks to the user - callers own their own replies and
translations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from kmua import database, enums
from kmua.bot.client import client
from kmua.logger import logger

# Synthetic sender ids that must never be treated as manageable users.
RESERVED_USER_IDS = frozenset(
    {
        int(enums.ChatID.ANONYMOUS_ADMIN),
        int(enums.ChatID.SERVICE_CHAT),
        int(enums.ChatID.FAKE_CHANNEL),
    }
)


class BotAdminResult(StrEnum):
    """Outcome of a bot-admin promotion or demotion."""

    OK = "ok"
    INVALID_TARGET = "invalid_target"
    TARGET_IS_UPSTREAM = "target_is_upstream"
    USER_NOT_FOUND = "user_not_found"
    USER_IS_BOT = "user_is_bot"
    USER_NOT_IN_CHAT = "user_not_in_chat"
    ALREADY_SET = "already_set"


async def set_bot_admin(
    *,
    chat_id: int,
    actor_id: int,
    target_id: int,
    promote: bool,
    actor_is_privileged: bool = False,
) -> BotAdminResult:
    """Promote or demote a bot admin in a chat.

    `actor_is_privileged` marks an owner or global admin, who bypasses the
    upstream check because they do not derive their rights from the chat.

    The upstream check is what keeps the delegation chain acyclic: an admin who
    was promoted by someone cannot demote that person back.
    """
    if target_id in RESERVED_USER_IDS or target_id == actor_id:
        return BotAdminResult.INVALID_TARGET

    if not actor_is_privileged:
        actor_association = await database.get_association(actor_id, chat_id)
        if actor_association is None or not actor_association.is_bot_admin:
            return BotAdminResult.TARGET_IS_UPSTREAM
        if (
            actor_association.promoted_by is not None
            and actor_association.promoted_by == target_id
        ):
            return BotAdminResult.TARGET_IS_UPSTREAM

    target = await database.get_user_by_id(target_id)
    if target is None:
        return BotAdminResult.USER_NOT_FOUND
    if target.is_bot:
        return BotAdminResult.USER_IS_BOT

    association = await database.get_association(target_id, chat_id)
    if association is None:
        return BotAdminResult.USER_NOT_IN_CHAT
    if association.is_bot_admin == promote:
        return BotAdminResult.ALREADY_SET

    ok = await database.set_association_bot_admin(
        target_id,
        chat_id,
        promote,
        promoted_by=actor_id if promote else None,
    )
    if not ok:
        return BotAdminResult.USER_NOT_IN_CHAT

    logger.info(
        f"[{chat_id}]({actor_id}): "
        f"{'promoted' if promote else 'demoted'} bot admin {target_id}"
    )
    return BotAdminResult.OK


@dataclass(slots=True)
class SyncMembersResult:
    """How many stale members a sync removed."""

    removed: int
    checked: int


async def sync_chat_members(chat_id: int) -> SyncMembersResult:
    """Drop members the bot recorded who are no longer in the chat.

    Raises on Telegram failures (usually missing admin rights) so callers can
    tell "nothing to do" apart from "could not look".
    """
    chat_data = await database.get_chat_by_id(chat_id)
    if chat_data is None:
        raise ValueError(f"Chat with id {chat_id} not found")

    current_member_ids = {
        member.user.id async for member in client.get_chat_members(chat_id)
    }

    associations = await database.get_chat_associations(chat_id)
    known_ids = {association.user_id for association in associations}
    stale_ids = known_ids - current_member_ids

    removed = 0
    for user_id in stale_ids:
        if not await database.remove_association(user_id, chat_id):
            logger.warning(
                f"Failed to remove association for user {user_id} in chat {chat_id}"
            )
            continue
        removed += 1
        await database.unset_chat_waifus_by_waifu(chat_data, user_id)

    logger.info(
        f"Synced members for chat {chat_id} ({chat_data.title}), removed {removed}"
    )
    return SyncMembersResult(removed=removed, checked=len(known_ids))


@dataclass(slots=True)
class DivorceResult:
    """Who the divorce affected, so the caller can notify the other side."""

    partner_id: int
    partner_name: str
    partner_lang: str


async def divorce_user(user_id: int) -> DivorceResult:
    """End a marriage and report the former partner.

    Raises `ValueError` when the user is not married or the partner record is
    missing.
    """
    user = await database.get_user_by_id(user_id)
    if user is None:
        raise ValueError(f"User with id {user_id} not found")
    if not user.is_married or user.married_waifu_id is None:
        raise ValueError("User is not married")

    partner = await database.get_user_by_id(user.married_waifu_id)
    if partner is None:
        raise ValueError("Married partner not found")

    partner_info = DivorceResult(
        partner_id=partner.id,
        partner_name=partner.full_name,
        partner_lang=partner.user_config.lang,
    )
    await database.divorce(user_id)
    return partner_info


async def collect_stats() -> dict[str, object]:
    """Aggregate the counters the /status command and the panel both show."""
    return {
        "users": await database.count_users(),
        "chats": await database.count_chats(),
        "quotes": await database.count_quotes(),
        "associations": await database.count_associations(),
        "bottles": await database.count_bottles(),
        "affection": await database.get_affection_stats(),
    }
