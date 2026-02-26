import dataclasses

import pyrogram
from pydantic_ai import (
    Agent,
    CallDeferred,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
)
from pydantic_ai.messages import ModelMessage
from pyrogram.client import Client
from pyrogram.types import CallbackQuery

from kmua import common, database, i18n
from kmua.common import memstore
from kmua.config import app_config
from kmua.logger import logger

from .. import datatype, state
from ..output import TypingKeepAlive, reply_output

# Module-level reference to agent instance (set by agent.py)
_agent = None
_model = None
_multimodal_model = None


def set_agent(agent, model=None, multimodal_model=None) -> None:
    """Set the agent instance reference for resume_ask."""
    global _agent, _model, _multimodal_model
    _agent = agent
    _model = model
    _multimodal_model = multimodal_model


_ASK_STATE_KEY_PREFIX = "agent_ask_state:"


@dataclasses.dataclass
class AskState:
    """State for a deferred ask operation."""

    options: list[str]
    tool_call_id: str
    question: str
    history: list[ModelMessage]


def _state_key(chat_id: int, user_id: int) -> str:
    return f"{_ASK_STATE_KEY_PREFIX}{chat_id}:{user_id}"


async def save_ask_state(chat_id: int, user_id: int, state: AskState) -> None:
    """Save the complete ask state."""
    await memstore.set(_state_key(chat_id, user_id), state)


async def get_ask_state(chat_id: int, user_id: int) -> AskState | None:
    """Get the saved ask state."""
    state: AskState | None = await memstore.get(_state_key(chat_id, user_id))
    return state


async def clear_ask_state(chat_id: int, user_id: int) -> None:
    """Clear the ask state."""
    await memstore.delete(_state_key(chat_id, user_id))


async def cancel_pending_asks(chat_id: int, user_id: int) -> None:
    """Cancel any pending asks for the user."""
    await clear_ask_state(chat_id, user_id)


async def resume_ask(
    client: Client,
    ask_state: AskState,
    answer: str,
    message: pyrogram.types.Message,
    powermemory=None,
    user_prompt: str | list | None = None,
    needs_multimodal: bool = False,
    user_id: int | None = None,
) -> None:
    """Resume agent run after getting an answer (or no answer) to a deferred ask.

    Args:
        client: The Pyrogram client.
        ask_state: The AskState containing all necessary data.
        answer: The user's answer, or a message indicating no answer.
        message: The message object for reply context.
        powermemory: Optional PowerMemory instance.
        user_prompt: Optional new user message (can be text or multimodal content list).
        needs_multimodal: Whether to use multimodal model.
        user_id: The user ID to use (overrides message.from_user.id). Required if message.from_user is None (e.g. callback query).
    """

    global _agent
    if _agent is None:
        logger.error("resume_ask: agent not set")
        return

    if not message.chat:
        logger.error("resume_ask: message.chat is None")
        return

    # When called from a callback_query handler, message is the bot's question message,
    # so message.from_user would be the bot itself. Use actual_user_id when provided.
    if user_id is not None:
        user_id = user_id
    elif message.from_user:
        user_id = message.from_user.id
    else:
        logger.error("resume_ask: cannot determine user_id")
        return

    chat_id = message.chat.id
    if chat_id is None:
        logger.error("resume_ask: chat_id is None")
        return

    assert chat_id is not None  # type: ignore

    await clear_ask_state(chat_id, user_id)

    deferred_results = DeferredToolResults()

    user_data = await database.get_user_by_id(user_id)
    if not user_data:
        return

    user_config = await database.get_user_config(user_id)
    lang = user_config.lang

    # Build the agent run kwargs.
    # IMPORTANT: pydantic-ai raises UserError if user_prompt is passed together with
    # deferred_tool_results when the history already ends with unprocessed tool calls.
    # To pass extra context (e.g. the new message the user sent instead of answering),
    # we embed it directly into the answer string rather than as a separate user_prompt.
    if user_prompt is not None:
        extra_text = user_prompt if isinstance(user_prompt, str) else str(user_prompt)
        answer = f"{answer}\n用户发送的新消息内容: {extra_text}"

    deferred_results.calls[ask_state.tool_call_id] = answer

    run_kwargs = {
        "message_history": ask_state.history,
        "deferred_tool_results": deferred_results,
        "deps": datatype.ContextDeps(
            user_id=user_id,
            chat_id=chat_id,
            message=message,
            client=client,
            powermemory=powermemory,
            history=list(ask_state.history),
        ),
    }

    # Use multimodal model if needed
    global _model, _multimodal_model
    use_model = _multimodal_model if needs_multimodal else _model

    await common.memstore.set(state.waiting_key(user_id), True)
    try:
        async with TypingKeepAlive(client, message):
            async with _agent.iter(model=use_model, **run_kwargs) as agent_run:  # type: ignore
                replied = False
                async for node in agent_run:
                    if Agent.is_call_tools_node(node):
                        # Log tool calls
                        for part in node.model_response.parts:
                            if part.part_kind == "tool-call":
                                args_str = str(part.args) if part.args else ""
                                logger.debug(
                                    f"Tool call: {part.tool_name}({args_str[:200]}...)"
                                )
                            elif part.part_kind == "text" and part.content:
                                await reply_output(client, message, part.content)
                                replied = True
                    elif Agent.is_end_node(node):
                        assert agent_run.result is not None
                        output = agent_run.result.output
                        if isinstance(output, DeferredToolRequests):
                            logger.info(
                                f"Agent returned DeferredToolRequests again for user {user_id}"
                            )
                        elif not replied and output:
                            await reply_output(client, message, output)
                await common.memttlcache.set(
                    state.history_key(chat_id, user_id),
                    agent_run.all_messages(),
                    ttl=app_config.cachettl_agent_history,
                )
    except Exception as e:
        logger.error(f"resume_ask error: {e.__class__.__name__} - {e}")
        await message.reply_text(
            i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
                error=f"{e.__class__.__name__}"
            )
        )
    finally:
        await common.memstore.delete(state.waiting_key(user_id))


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
        The user's answer as a plain string (the text of the chosen option).
    """
    if not options or len(options) < 2:
        raise ModelRetry("Provide at least 2 options.")
    if len(options) > 5:
        raise ModelRetry("Provide at most 5 options.")
    if not question.strip():
        raise ModelRetry("Question must not be empty.")
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        raise ModelRetry("Message context is unavailable.")

    user_id = ctx.deps.user_id
    chat_id = ctx.deps.chat_id
    tool_call_id = ctx.tool_call_id

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
        logger.error(f"ask_user: failed to send question: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send question: {e.__class__.__name__}")

    await memstore.set(
        _state_key(chat_id, user_id),
        AskState(
            options=list(options),
            tool_call_id=tool_call_id or "",
            question=question,
            history=[],  # Will be filled by agent.py when saving
        ),
    )

    raise CallDeferred(metadata={"question": question, "options_count": len(options)})


async def update_ask_history(
    chat_id: int, user_id: int, history: list[ModelMessage]
) -> None:
    """Update the history in the ask state.

    Called by agent.py when DeferredToolRequests is returned.
    """
    state = await get_ask_state(chat_id, user_id)
    if state is not None:
        state.history = list(history)
        await save_ask_state(chat_id, user_id, state)


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

    state = await get_ask_state(expected_chat_id, expected_user_id)
    if state is None:
        await callback_query.answer("这条回答已经过期了哦", show_alert=True)
        return

    try:
        opt_index = int(opt_id_str)
        answer = state.options[opt_index]
    except (ValueError, IndexError):
        await callback_query.answer("无效的选项", show_alert=True)
        return
    # Immediately clear state to prevent multiple selections
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
        if not chat_id or not isinstance(markup, pyrogram.types.InlineKeyboardMarkup):
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

    # Use the centralized resume function
    # NOTE: msg is the bot's question message, so msg.from_user would be the bot itself.
    # We must pass the actual user via from_user override.
    await resume_ask(
        client=client,
        ask_state=state,
        answer=answer,
        message=msg,
        user_id=expected_user_id,
    )


__all__ = [
    "ask_user",
    "resume_ask",
    "AskState",
    "save_ask_state",
    "get_ask_state",
    "update_ask_history",
    "clear_ask_state",
    "cancel_pending_asks",
    "set_agent",
]
