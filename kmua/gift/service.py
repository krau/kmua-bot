"""Gift operations shared by Telegram callbacks and the Mini App."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from kmua import affection, common, database, gift
from kmua.plugins.agent import state

# Gift effects touch both the database and short-lived in-memory state, which cannot
# share one transaction. kmua runs as one process, so a narrow process-local lock keeps
# a double tap or parallel HTTP request from applying an effect twice while retaining
# the existing order: a failed effect does not consume the gift.
_gift_send_lock = asyncio.Lock()


@dataclass(frozen=True)
class GiftUseResult:
    display_name: str
    rarity_name: str
    detail: str | None = None


async def send_gift_to_bot(user_id: int, gift_db_id: int) -> GiftUseResult:
    """Consume one of a user's gifts and apply its effect.

    The caller owns the gift id indirectly through their authenticated user id. Keeping
    that check here means the panel and the callback cannot drift into different rules.
    """
    async with _gift_send_lock:
        return await _send_gift_to_bot(user_id, gift_db_id)


async def _send_gift_to_bot(user_id: int, gift_db_id: int) -> GiftUseResult:
    gift_item = await database.get_gift_by_db_id(gift_db_id)
    if gift_item is None:
        raise ValueError("Gift not found")
    if gift_item.owner_id != user_id:
        raise ValueError("This is not your gift")
    if gift_item.sent_to_bot:
        raise ValueError("Gift was already sent")
    try:
        gift_id = gift.GiftID(gift_item.gift_id)
    except ValueError as e:
        raise ValueError("Unknown gift") from e
    if gift_id not in gift.ALL_GIFTS:
        # Keep the callback's old behaviour: sentinel/invalid gifts are never consumed.
        raise ValueError("Unknown gift")

    gift_def = gift.get_gift_by_id(gift_id)
    detail: str | None = None
    match gift_def.id:
        case gift.GiftID.SEVERED_GRASS_SILENCE:
            await common.memttlcache.delete(f"agent_user_memory:{user_id}")
        case gift.GiftID.VOW_LOTUS_SEAL:
            duration = gift_def.effects.get("duration", 0) * gift_item.rarity
            passivation = gift_def.effects.get("passivation", 0) * gift_item.rarity
            await common.memttlcache.set(
                f"affection_passivation:{user_id}", passivation, duration
            )
        case gift.GiftID.AMARANTH_HEART_LAMP:
            current = await affection.get_user_affection(user_id)
            add_affection = gift_def.effects.get("add_affection", 0) * gift_item.rarity
            duration = gift_def.effects.get("duration", 0) * gift_item.rarity
            await affection.set_user_temporary_affection(
                user_id=user_id,
                affection=current + add_affection,
                ttl=duration,
            )
        case gift.GiftID.FROST_FLOWER_WHISPER:
            memory = await common.memttlcache.get(f"agent_user_memory:{user_id}")
            affection_rank = await affection.get_affection_rank(user_id)
            detail = (
                f"当前对你的记忆:\n{memory or '无'}\n\n好感度排名: {affection_rank:.2%}"
            )
        case gift.GiftID.DAWN_BELL_HERB:
            await common.memttlcache.delete(state.user_blocked_key(user_id))
            immune_duration = (
                gift_def.effects.get("immune_duration", 0) * gift_item.rarity
            )
            if immune_duration > 0:
                await common.memttlcache.set(
                    state.user_block_immune_key(user_id), True, ttl=immune_duration
                )

    affection_change = gift_def.effects.get("affection_change", 0)
    if affection_change:
        await affection.update_user_affection(user_id=user_id, change=affection_change)
    await database.mark_gift_as_sent(gift_db_id)
    return GiftUseResult(
        display_name=gift.get_display_name(gift_def.id),
        rarity_name=gift.get_rarity_display_name(gift_item.rarity),
        detail=detail,
    )
