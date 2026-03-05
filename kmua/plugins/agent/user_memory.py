import asyncio
import random
from weakref import WeakValueDictionary

from pydantic_ai import Agent, ModelRetry

from kmua import affection
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state

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

        # 使用超时控制防止模型调用阻塞事件循环
        timeout = app_config.agent_model_timeout
        coro = agent.run(
            output_type=datatype.UserMemoryResult,
            user_prompt=f"根据以下聊天消息, 总结出关于用户的重要信息, 并决定对用户的好感变化:\n {message_text}",
        )

        if timeout > 0:
            try:
                memory_result = await asyncio.wait_for(coro, timeout=timeout)
            except TimeoutError:
                logger.warning(f"update_user_memory timed out for user {user_id}")
                return  # 超时后静默返回，不影响主流程
        else:
            memory_result = await coro

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
