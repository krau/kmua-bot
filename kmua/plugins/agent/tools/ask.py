import dataclasses

import pyrogram
from pydantic_ai import ModelRetry, RunContext
from pyrogram.client import Client
from pyrogram.types import CallbackQuery

from kmua import database
from kmua.common import memstore
from kmua.config import app_config
from kmua.logger import logger

from .. import datatype
from ..whitelist import is_chat_allowed

_ASK_STATE_KEY_PREFIX = "agent_ask_state:"


@dataclasses.dataclass
class AskState:
    """Minimal state for a pending ask — just the question and options."""

    options: list[str]
    question: str


def _state_key(chat_id: int, user_id: int) -> str:
    return f"{_ASK_STATE_KEY_PREFIX}{chat_id}:{user_id}"


async def get_ask_state(chat_id: int, user_id: int) -> AskState | None:
    return await memstore.get(_state_key(chat_id, user_id))


async def clear_ask_state(chat_id: int, user_id: int) -> None:
    await memstore.delete(_state_key(chat_id, user_id))


async def ask_user(
    ctx: RunContext[datatype.ContextDeps],
    question: str,
    options: list[str],
) -> datatype.AskUserOutput:
    """Ask the user a question and wait for their answer.

    Use this tool to clarify ambiguous requests, collect preferences, or let the
    user choose between implementation options before proceeding.

    Args:
        question: The question to present to the user.
        options: 2-5 short option labels for the user to choose from.
    """
    if not options or len(options) < 2:
        raise ModelRetry("Provide at least 2 options.")
    if len(options) > 5:
        raise ModelRetry("Provide at most 5 options.")
    if not question.strip():
        raise ModelRetry("Question must not be empty.")
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        raise ModelRetry("Message context is unavailable.")
    if not is_chat_allowed(ctx.deps.chat_id):
        raise ModelRetry("This feature is not available in this chat.")

    user_id = ctx.deps.user_id
    chat_id = ctx.deps.chat_id

    rows = [
        [
            pyrogram.types.InlineKeyboardButton(
                text=opt,
                callback_data=f"agentask:{chat_id}:{user_id}:{i}",
            )
        ]
        for i, opt in enumerate(options)
    ]

    try:
        await ctx.deps.client.send_message(
            chat_id=chat_id,
            text=question,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(rows),
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
    except Exception as e:
        logger.error(f"ask_user: failed to send question: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send question: {e.__class__.__name__}")

    await memstore.set(
        _state_key(chat_id, user_id),
        AskState(options=list(options), question=question),
    )

    return datatype.AskUserOutput(question=question)


# Callback to trigger a new agent run — set by agent.py at init time.
_run_agent_for_ask = None


def set_run_callback(callback) -> None:
    """Register the function that starts a new agent run for ask answers."""
    global _run_agent_for_ask
    _run_agent_for_ask = callback


@Client.on_callback_query(
    pyrogram.filters.regex(r"^agentask:(-?\d+):(-?\d+):(\d+)$"), group=0
)
async def _on_ask_answer(client: Client, callback_query: CallbackQuery) -> None:
    if not app_config.agent:
        return
    data = str(callback_query.data)
    parts = data.split(":")
    if len(parts) != 4:
        return
    _, chat_id_str, uid_str, opt_id_str = parts

    expected_user_id = int(uid_str)
    expected_chat_id = int(chat_id_str)
    if not is_chat_allowed(expected_chat_id):
        return
    caller_id = callback_query.from_user.id if callback_query.from_user else None
    if caller_id != expected_user_id:
        await callback_query.answer("这不是你的问题哦", show_alert=True)
        return

    ask_state = await get_ask_state(expected_chat_id, expected_user_id)
    if ask_state is None:
        await callback_query.answer("这条回答已经过期了哦", show_alert=True)
        return

    try:
        opt_index = int(opt_id_str)
        answer = ask_state.options[opt_index]
    except (ValueError, IndexError):
        await callback_query.answer("无效的选项", show_alert=True)
        return

    await clear_ask_state(expected_chat_id, expected_user_id)
    await callback_query.answer()

    msg = callback_query.message
    if msg is None:
        logger.error("ask_answer: callback_query.message is None")
        return

    # Update keyboard to show selected option
    try:
        chat_id = msg.chat.id if msg.chat else None
        markup = msg.reply_markup
        if chat_id and isinstance(markup, pyrogram.types.InlineKeyboardMarkup):
            new_rows = []
            for row in markup.inline_keyboard:
                new_row = []
                for btn in row:
                    cb = btn.callback_data
                    cb_str = cb.decode() if isinstance(cb, bytes) else (cb or "")
                    if cb_str == data:
                        new_row.append(
                            pyrogram.types.InlineKeyboardButton(
                                text=f"✅ {btn.text}",
                                callback_data=cb_str,
                            )
                        )
                    else:
                        new_row.append(btn)
                new_rows.append(new_row)
            await client.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg.id,
                reply_markup=pyrogram.types.InlineKeyboardMarkup(new_rows),
            )
    except Exception as e:
        logger.error(
            f"ask_answer: failed to update keyboard: {e.__class__.__name__}: {e}"
        )

    # Start a new agent run with the user's answer as the prompt.
    if _run_agent_for_ask is None:
        logger.error("ask_answer: run callback not set")
        return

    user_data = await database.get_user_by_id(expected_user_id)
    if not user_data:
        return

    answer_prompt = f"用户对问题「{ask_state.question}」的回答是: {answer}"
    await _run_agent_for_ask(
        client=client,
        message=msg,
        user_id=expected_user_id,
        chat_id=expected_chat_id,
        user_prompt=answer_prompt,
    )


__all__ = [
    "ask_user",
    "AskState",
    "get_ask_state",
    "clear_ask_state",
    "set_run_callback",
]
