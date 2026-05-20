from pydantic_ai import RunContext
from pyrogram.enums import ChatMemberStatus

from kmua import common
from kmua.affection import get_affection_rank
from kmua.logger import logger

from .. import datatype, state


def _calculate_block_duration(requested_minutes: int, affection_rank: float) -> int:
    """Calculate effective block duration based on affection rank.

    Formula: effective = requested * max(0.1, 1 - affection_rank^2)

    - affection_rank 0.0 (lowest): factor = 1.0, no reduction
    - affection_rank 0.5: factor = 0.75
    - affection_rank 0.8: factor = 0.36
    - affection_rank 1.0 (highest): factor = 0.1, minimum 10%
    """
    factor = max(0.1, 1.0 - affection_rank**2)
    return max(1, round(requested_minutes * factor))


async def block_user(
    ctx: RunContext[datatype.ContextDeps],
    duration_minutes: int,
    user_id: int | None = None,
    reason: str = "",
) -> str:
    """Block a user from triggering you for a specified duration.

    The user will not be able to trigger any response from you until the block expires.

    Args:
        duration_minutes: Requested block duration in minutes (1~10080, i.e. 1 minute to 7 days).
        user_id: The Telegram user ID to block. If not provided, defaults to the current user.
        reason: Brief reason for blocking this user (optional).

    Returns:
        A description of the block result including the actual duration.
    """
    duration_minutes = max(1, min(10080, duration_minutes))

    target_id = user_id if user_id is not None else ctx.deps.user_id

    is_group = ctx.deps.chat_id < -100
    if is_group and user_id is not None:
        try:
            member = await common.get_chat_member(
                ctx.deps.client, ctx.deps.chat_id, user_id
            )
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                return f"User {user_id} is not a member of this group, cannot block."
        except Exception as e:
            logger.warning(f"Failed to check membership for user {user_id}: {e}")
            return f"Cannot verify if user {user_id} is in this group: {e.__class__.__name__}"

    affection_rank = await get_affection_rank(target_id)
    effective_minutes = _calculate_block_duration(duration_minutes, affection_rank)
    ttl_seconds = effective_minutes * 60

    await common.memttlcache.set(
        state.user_blocked_key(target_id), True, ttl=ttl_seconds
    )

    logger.info(
        f"User {target_id} blocked by agent for {effective_minutes} minutes "
        f"(requested: {duration_minutes}, affection_rank: {affection_rank:.4f}, "
        f"reason: {reason!r})"
    )

    return (
        f"User {target_id} has been blocked for {effective_minutes} minutes "
        f"(requested {duration_minutes} min, reduced by affection rank)."
    )


async def is_user_blocked(user_id: int) -> bool:
    """Check if a user is currently blocked from triggering the agent."""
    return bool(await common.memttlcache.get(state.user_blocked_key(user_id)))
