import asyncio
import secrets

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
_USER_TOKENS_PREFIX = "agent_ask_user_tokens:"


def _pending_key(token: str) -> str:
    return f"{_PENDING_KEY_PREFIX}{token}"


def _options_key(token: str) -> str:
    return f"{_OPTIONS_KEY_PREFIX}{token}"


def _user_tokens_key(user_id: int) -> str:
    return f"{_USER_TOKENS_PREFIX}{user_id}"


async def _register_token(user_id: int, token: str) -> None:
    tokens: set[str] = await memstore.get(_user_tokens_key(user_id), set())
    tokens.add(token)
    await memstore.set(_user_tokens_key(user_id), tokens)


async def _unregister_token(user_id: int, token: str) -> None:
    tokens: set[str] = await memstore.get(_user_tokens_key(user_id), set())
    tokens.discard(token)
    if tokens:
        await memstore.set(_user_tokens_key(user_id), tokens)
    else:
        await memstore.delete(_user_tokens_key(user_id))


async def cancel_pending_asks(user_id: int) -> None:
    tokens: set[str] = await memstore.get(_user_tokens_key(user_id), set())
    for token in list(tokens):
        future: asyncio.Future[str] | None = await memstore.get(_pending_key(token))
        if future is not None and not future.done():
            future.cancel()
        await memstore.delete(_pending_key(token))
        await memstore.delete(_options_key(token))
    await memstore.delete(_user_tokens_key(user_id))


async def ask_user(
    ctx: RunContext[datatype.ContextDeps],
    question: str,
    options: list[str],
) -> str:
    """Ask the user a question via an inline keyboard and wait for their answer.

    Use this tool to clarify ambiguous requests, collect preferences, or let the
    user choose between implementation options before proceeding.  Call it at most
    once per agent turn — if more than one thing is unclear, combine them into a
    single question with clearly labelled options.

    Args:
        question: The question to present to the user.
        options: 2–5 short option labels for the user to choose from.

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

    token = secrets.token_hex(8)
    loop = asyncio.get_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    await memstore.set(_pending_key(token), future)
    await memstore.set(_options_key(token), list(options))
    await _register_token(ctx.deps.user_id, token)

    rows: list[list[pyrogram.types.InlineKeyboardButton]] = [
        [
            pyrogram.types.InlineKeyboardButton(
                text=opt,
                callback_data=f"ask:{token}:{i}",
            )
        ]
        for i, opt in enumerate(options)
    ]

    try:
        await ctx.deps.client.send_message(
            chat_id=ctx.deps.chat_id,
            text=question,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(rows),
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
    except Exception as e:
        await memstore.delete(_pending_key(token))
        await memstore.delete(_options_key(token))
        await _unregister_token(ctx.deps.user_id, token)
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
        await memstore.delete(_pending_key(token))
        await memstore.delete(_options_key(token))
        await _unregister_token(ctx.deps.user_id, token)


@Client.on_callback_query(pyrogram.filters.regex(r"^ask:([^:]+):(\d+)$"), group=0)
async def _on_ask_answer(client: Client, callback_query: CallbackQuery) -> None:
    raw = callback_query.data or b""
    data = raw.decode() if isinstance(raw, bytes) else raw
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, token, opt_id_str = parts

    options: list[str] | None = await memstore.get(_options_key(token))
    future: asyncio.Future[str] | None = await memstore.get(_pending_key(token))

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
