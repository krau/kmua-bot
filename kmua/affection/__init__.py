import math

from kmua import common, database
from kmua.logger import logger


def calculate_affection_update(
    current, change, rank, passivation=0.05, limit=2000, p=2, q=2, min_damping=0.2
) -> int:
    if change == 0:
        return current
    return round(
        max(
            -limit,
            min(
                limit,
                (
                    current
                    + (
                        change
                        * (
                            math.tanh(passivation * change / limit)
                            / (passivation * change / limit)
                        )
                        * max(
                            (1.0 / (1.0 + passivation * abs(2 * rank - 1) ** q))
                            * (max(0.0, 1.0 - (abs(current) / limit) ** p)),
                            min_damping,
                        )
                    )
                ),
            ),
        )
    )


async def set_user_temporary_affection(user_id: int, affection: int, ttl: int):
    await common.memttlcache.set(f"user_affection:{user_id}", affection, ttl=ttl)


async def get_user_affection(user_id: int) -> int:
    affection = await common.memttlcache.get(f"user_affection:{user_id}", None)
    if affection is not None:
        return affection
    user_config = await database.get_user_config(user_id)
    return user_config.affection


async def get_affection_rank(user_id: int) -> float:
    current_affection = await get_user_affection(user_id)
    rank = await database.get_affection_percentile(current_affection)
    return rank


async def update_user_affection(user_id: int, change: int):
    current_affection = await get_user_affection(user_id)
    rank = await database.get_affection_percentile(current_affection)
    passivation = await common.memttlcache.get(f"affection_passivation:{user_id}", None)
    if passivation is None:
        passivation = min(5.0, 0.005 + 10 * abs(0.5 - rank))
    new_affection = calculate_affection_update(
        current=current_affection,
        change=change,
        rank=rank,
        passivation=passivation,
    )
    await database.update_user_affection(user_id, new_affection)
    logger.info(
        f"User {user_id} affection updated from {current_affection} to {new_affection} (change: {change}, rank: {rank:.4f}, passivation: {passivation:.4f})"
    )
