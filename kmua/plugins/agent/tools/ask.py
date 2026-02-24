import asyncio

import pyrogram
from pydantic_ai import ModelRetry, RunContext
from pyrogram.client import Client
from pyrogram.types import CallbackQuery

from kmua.common import memstore
from kmua.logger import logger

from .. import datatype

_ASK_TIMEOUT = 120
_PENDING_KEY_PREFIX = "agent_ask_pending:"
_OPTIONS_KEY_PREFIX = "agent_ask_options:"


def _pending_key(chat_id: int, user_id: int) -> str:
    return f"{_PENDING_KEY_PREFIX}{chat_id}:{user_id}"


def _options_key(chat_id: int, user_id: int) -> str:
    return f"{_OPTIONS_KEY_PREFIX}{chat_id}:{user_id}"


async def cancel_pending_asks(chat_id: int, user_id: int) -> None:
    future: asyncio.Future[str] | None = await memstore.get(
        _pending_key(chat_id, user_id)
    )
    if future is not None and not future.done():
        future.cancel()
    await memstore.delete(_pending_key(chat_id, user_id))
    await memstore.delete(_options_key(chat_id, user_id))


async def ask_user(
    ctx: RunContext[datatype.ContextDeps],
    question: str,
    options: list[str],
) -> str:
    """Ask the user a question and wait for their answer.

    Use this tool to clarify ambiguous requests, collect preferences, or let the
    user choose between implementation options before proceeding.

    Args:
        question: The question to present to the user.
        options: 2-5 short option labels for the user to choose from.

    Returns:
        The user's answer as a plain string (the text of the chosen option),
        or a message explaining why no answer was received.
    """
    logger.debug(
        f"ask_user called with question='{question}' and options={options} for user_id={ctx.deps.user_id} in chat_id={ctx.deps.chat_id}"
    )
    if not options or len(options) < 2:
        raise ModelRetry("Provide at least 2 options.")
    if len(options) > 5:
        raise ModelRetry("Provide at most 5 options.")
    if not question.strip():
        raise ModelRetry("Question must not be empty.")
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return "Message context is unavailable."

    user_id = ctx.deps.user_id
    chat_id = ctx.deps.chat_id
    loop = asyncio.get_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    await memstore.set(_pending_key(chat_id, user_id), future)
    await memstore.set(_options_key(chat_id, user_id), list(options))

    rows: list[list[pyrogram.types.InlineKeyboardButton]] = [
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
        await memstore.delete(_pending_key(chat_id, user_id))
        await memstore.delete(_options_key(chat_id, user_id))
        logger.error(f"ask_user: failed to send question: {e.__class__.__name__}: {e}")
        return f"Failed to send question: {e.__class__.__name__}"

    try:
        answer = await asyncio.wait_for(asyncio.shield(future), timeout=_ASK_TIMEOUT)
        return answer
    except TimeoutError:
        return "The user did not respond in time."
    except asyncio.CancelledError:
        return "The question was cancelled because the user started a new conversation."
    finally:
        await memstore.delete(_pending_key(chat_id, user_id))
        await memstore.delete(_options_key(chat_id, user_id))


@Client.on_callback_query(
    pyrogram.filters.regex(r"^agentask:(-?\d+):(-?\d+):(\d+)$"), group=0
)
async def _on_ask_answer(client: Client, callback_query: CallbackQuery) -> None:
    data = str(callback_query.data)
    parts = data.split(":")
    if len(parts) != 4:
        return
    _, chat_id_str, uid_str, opt_id_str = parts

    expected_user_id = int(uid_str)
    expected_chat_id = int(chat_id_str)
    caller_id = callback_query.from_user.id if callback_query.from_user else None
    if caller_id != expected_user_id:
        await callback_query.answer("这不是你的问题哦", show_alert=True)
        return

    options: list[str] | None = await memstore.get(
        _options_key(expected_chat_id, expected_user_id)
    )
    future: asyncio.Future[str] | None = await memstore.get(
        _pending_key(expected_chat_id, expected_user_id)
    )

    if future is None or future.done() or options is None:
        await callback_query.answer("这条回答已经过期了哦", show_alert=True)
        return

    try:
        opt_index = int(opt_id_str)
        answer = options[opt_index]
    except (ValueError, IndexError):
        await callback_query.answer("无效的选项", show_alert=True)
        return

    future.set_result(answer)
    await callback_query.answer()

    try:
        msg = callback_query.message
        chat_id = msg.chat.id if msg and msg.chat else None
        markup = msg.reply_markup if msg else None
        if (
            not chat_id
            or not msg
            or not isinstance(markup, pyrogram.types.InlineKeyboardMarkup)
        ):
            return
        new_rows: list[list[pyrogram.types.InlineKeyboardButton]] = []
        for row in markup.inline_keyboard:
            new_row: list[pyrogram.types.InlineKeyboardButton] = []
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


__all__ = ["ask_user", "cancel_pending_asks"]
