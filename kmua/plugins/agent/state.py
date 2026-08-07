import asyncio
from typing import Any


def history_key(chat_id: int, user_id: int) -> str:
    return f"message_history_with_agent:{chat_id}:{user_id}"


def waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


# Per-conversation turn ownership. The wake/ask/guest/follow-up entries
# acquire the lock for the whole run; a second message finding it locked is
# an interjection and gets queued instead of starting a concurrent run.
_conversation_locks: dict[tuple[int, int], asyncio.Lock] = {}


_MAX_CONVERSATION_LOCKS = 512


def get_conversation_lock(chat_id: int, user_id: int) -> asyncio.Lock:
    """The (chat, user) turn lock, created on first use.

    Unlocked locks are pruned once the registry outgrows a bound, so long
    runs with many distinct conversations do not grow without limit. A
    locked (in-flight) lock is never pruned.
    """
    key = (chat_id, user_id)
    lock = _conversation_locks.get(key)
    if lock is None:
        if len(_conversation_locks) >= _MAX_CONVERSATION_LOCKS:
            for existing_key, existing in list(_conversation_locks.items()):
                if not existing.locked():
                    del _conversation_locks[existing_key]
        lock = asyncio.Lock()
        _conversation_locks[key] = lock
    return lock


def is_running(chat_id: int, user_id: int) -> bool:
    """Whether a turn is in flight for this conversation."""
    lock = _conversation_locks.get((chat_id, user_id))
    return lock is not None and lock.locked()


def bot_last_reply_key(chat_id: int) -> str:
    """存储bot在某个群组最后一条回复的信息"""
    return f"bot_last_reply:{chat_id}"


def message_follow_up_lock_key(chat_id: int, message_id: int) -> str:
    """防止对同一条消息重复处理follow-up"""
    return f"message_follow_up_lock:{chat_id}:{message_id}"


def user_messages_global_key(user_id: int) -> str:
    return f"user_messages_global:{user_id}"


def user_memory_update_key(user_id: int) -> str:
    return f"user_memory_last_update_from_cross_group:{user_id}"


def memory_key(user_id: int) -> str:
    return f"agent_user_memory:{user_id}"


def group_messages_key(chat_id: int) -> str:
    return f"group_messages:{chat_id}"


def group_memory_update_key(chat_id: int) -> str:
    return f"group_memory_last_update:{chat_id}"


def last_edited_image_key(chat_id: int, user_id: int) -> str:
    return f"agent_last_edited_image_fileid:{chat_id}:{user_id}"


def last_user_image_key(chat_id: int, user_id: int) -> str:
    return f"agent_last_user_image_fileid:{chat_id}:{user_id}"


def chat_model_override_key(chat_id: int, role: str = "main") -> str:
    """Per-chat model override key. role: 'main' | 'multimodal' | 'small' (or any future role)."""
    return f"agent_chat_model_override:{role}:{chat_id}"


def periodic_sticker_counter_key(chat_id: int, user_id: int) -> str:
    """Conversation counter for periodic sticker forcing."""
    return f"agent_periodic_sticker_counter:{chat_id}:{user_id}"


def periodic_reaction_counter_key(chat_id: int, user_id: int) -> str:
    """Conversation counter for periodic reaction forcing."""
    return f"agent_periodic_reaction_counter:{chat_id}:{user_id}"


def chat_prompt_override_key(chat_id: int) -> str:
    """Per-chat system prompt override. Replaces the default prompt for this chat."""
    return f"agent_chat_prompt_override:{chat_id}"


def user_blocked_key(user_id: int) -> str:
    """Whether the user is blocked from triggering the agent."""
    return f"agent_user_blocked:{user_id}"


def user_block_immune_key(user_id: int) -> str:
    """Whether the user is immune to being blocked by the agent."""
    return f"agent_user_block_immune:{user_id}"


# Interjections: messages the user sends while their agent turn is running.
# Delivered straight into the live AgentRun (state.enqueue_interjection);
# this queue only covers the window before a run is registered or after it
# ends. A capability drains it as a fallback.
_steering_messages: dict[tuple[int, int], list[str]] = {}


_MAX_STEERING_MESSAGES = 20
_MAX_STEERING_CHARS = 8000


def queue_steering(chat_id: int, user_id: int, text: str) -> bool:
    """Queue a user interjection for the running turn.

    Bounded: an over-limit queue rejects the newest message instead of
    growing without limit into an oversized model request. Returns False
    when the message was not queued so the caller can tell the user.
    """
    from kmua.logger import logger

    key = (chat_id, user_id)
    queue = _steering_messages.setdefault(key, [])
    if len(queue) >= _MAX_STEERING_MESSAGES or (
        sum(len(item) for item in queue) + len(text) > _MAX_STEERING_CHARS
    ):
        logger.warning(
            f"Steering queue full for chat {chat_id} user {user_id}; "
            f"dropping the newest message"
        )
        return False
    queue.append(text)
    return True


def drain_steering(chat_id: int, user_id: int) -> list[str]:
    """Take and clear the queued interjections for a conversation."""
    return _steering_messages.pop((chat_id, user_id), [])


def peek_steering(chat_id: int, user_id: int) -> list[str]:
    """Copy of the queued interjections without clearing them."""
    return list(_steering_messages.get((chat_id, user_id), []))


def clear_steering(chat_id: int, user_id: int) -> None:
    """Drop the queued interjections of one conversation (history cleared),
    and its interjection budget so a fresh run starts with a full quota."""
    _steering_messages.pop((chat_id, user_id), None)
    _interjection_budget.pop((chat_id, user_id), None)


def clear_all_steering() -> int:
    count = sum(len(q) for q in _steering_messages.values())
    _steering_messages.clear()
    _interjection_budget.clear()
    return count


# The AgentRun currently executing for each conversation. Interjections
# enqueue into it directly (same event loop, safe from any task), so the
# pending-message drain delivers them on the very next model request - or
# via the end-of-run redirect - without waiting for a capability hook.
_active_runs: dict[tuple[int, int], Any] = {}


def register_active_run(chat_id: int, user_id: int, agent_run: Any) -> None:
    _active_runs[(chat_id, user_id)] = agent_run


def unregister_active_run(chat_id: int, user_id: int) -> None:
    _active_runs.pop((chat_id, user_id), None)
    _interjection_budget.pop((chat_id, user_id), None)


def get_active_run(chat_id: int, user_id: int) -> Any | None:
    return _active_runs.get((chat_id, user_id))


# Per-run interjection budget: the same caps as the steering queue apply to
# direct enqueue calls, so a run cannot accumulate unbounded pending input.
_interjection_budget: dict[tuple[int, int], tuple[int, int]] = {}


def enqueue_interjection(chat_id: int, user_id: int, text: str) -> bool:
    """Budget-checked enqueue into the live AgentRun (or the fallback queue).

    A run whose graph already ended (``result`` populated) is not enqueued
    into: its pending queue would never be drained. Returns False when the
    budget is exhausted or the fallback queue rejects; the budget is only
    charged on success and resets when the run ends.
    """
    key = (chat_id, user_id)
    count, chars = _interjection_budget.get(key, (0, 0))
    if count >= _MAX_STEERING_MESSAGES or (chars + len(text) > _MAX_STEERING_CHARS):
        return False
    run = _active_runs.get(key)
    if run is not None and run.result is None:
        run.enqueue(text, priority="asap")
    elif not queue_steering(chat_id, user_id, text):
        return False
    _interjection_budget[key] = (count + 1, chars + len(text))
    return True


def clear_all_locks() -> None:
    """Drop the conversation-lock registry (session-wide cleanup)."""
    _conversation_locks.clear()
