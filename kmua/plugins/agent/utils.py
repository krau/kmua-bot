import pyrogram

from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.plugins.agent import state

from .history import (
    filter_tool_return_if_needed,
    get_history_text,
    get_history_token_count,
    should_compress_by_tokens,
    summarize_history,
)
from .output import StreamingOutput, TypingKeepAlive, reply_output
from .prompt import (
    build_ctx_info,
    check_needs_multimodal,
    get_agent_affection_prompt,
    get_input_prompt,
)
from .runner import run_agent
from .user_memory import update_user_memory

__all__ = [
    # output
    "reply_output",
    "TypingKeepAlive",
    "StreamingOutput",
    # history
    "get_history_text",
    "get_history_token_count",
    "filter_tool_return_if_needed",
    "summarize_history",
    "should_compress_by_tokens",
    # prompt
    "get_input_prompt",
    "build_ctx_info",
    "check_needs_multimodal",
    "get_agent_affection_prompt",
    # runner
    "run_agent",
    # memory
    "update_user_memory",
    # local
    "cache_user_image",
]


def _extract_image_file_id(message: pyrogram.types.Message) -> str | None:
    if message.photo:
        return message.photo.file_id
    if (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("image/")
    ):
        return message.document.file_id
    return None


async def cache_user_image(
    message: pyrogram.types.Message,
    chat_id: int,
    user_id: int,
) -> None:
    file_id = _extract_image_file_id(message)
    if file_id is None and message.reply_to_message:
        file_id = _extract_image_file_id(message.reply_to_message)
    if file_id is None:
        return
    await memttlcache.set(
        state.last_user_image_key(chat_id, user_id),
        file_id,
        ttl=app_config.cachettl_agent_history,
    )
