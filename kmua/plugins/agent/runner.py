import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pydantic_ai
import pyrogram
from pydantic_ai import (
    Agent,
    UserContent,
)
from pydantic_ai.messages import (
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pyrogram.client import Client as PyrogramClient
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.agent import datatype, provider, safety, state
from kmua.plugins.agent.cache_stats import log_run_cache_stats
from kmua.plugins.agent.datatype import AskUserOutput, EndTurn
from kmua.plugins.agent.output import StreamingOutput, TypingKeepAlive, reply_output
from kmua.plugins.agent.prompt import (
    check_needs_multimodal,
    transcribe_multimodal_content,
    transcribe_multimodal_history,
)
from kmua.plugins.agent.whitelist import is_chat_allowed


async def get_chat_model_override(chat_id: int, role: str = "main") -> str | None:
    """Return the per-chat model override spec for the given role, or None if not set."""
    return await memttlcache.get(state.chat_model_override_key(chat_id, role))


async def set_chat_model_override(
    chat_id: int, model_spec: str | None, role: str = "main"
) -> None:
    """Set (or clear, when model_spec is None) the per-chat model override for the given role."""
    key = state.chat_model_override_key(chat_id, role)
    if model_spec is None:
        await memttlcache.delete(key)
    else:
        await memttlcache.set(key, model_spec)


async def get_chat_prompt_override(chat_id: int) -> str | None:
    """Return the per-chat system prompt override, or None if not set."""
    return await memttlcache.get(state.chat_prompt_override_key(chat_id))


async def set_chat_prompt_override(chat_id: int, prompt: str | None) -> None:
    """Set (or clear, when prompt is None) the per-chat system prompt override."""
    key = state.chat_prompt_override_key(chat_id)
    if prompt is None:
        await memttlcache.delete(key)
    else:
        await memttlcache.set(key, prompt)


@asynccontextmanager
async def _iter_with_spill_session(
    agi: Agent[Any, Any],
    *,
    chat_id: int,
    user_id: int,
    model: Any,
    model_settings: Any,
    user_prompt: Any,
    instructions: Any,
    message_history: Any,
    deps: Any,
    usage_limits: Any,
):
    """Run agi.iter with the current (chat, user) bound as the spill session,
    so spilled tool outputs are scoped to this conversation."""
    token = safety.set_spill_session(f"{chat_id}_{user_id}")
    try:
        async with agi.iter(
            model=model,
            model_settings=model_settings,
            user_prompt=user_prompt,
            instructions=instructions,
            message_history=message_history,
            deps=deps,
            usage_limits=usage_limits,
        ) as agent_run:
            # Interjections enqueue straight into this run (see
            # state.get_active_run), so the pending-message drain delivers
            # them on the next model request without a hook round-trip.
            state.register_active_run(chat_id, user_id, agent_run)
            yield agent_run
    finally:
        state.unregister_active_run(chat_id, user_id)
        safety.reset_spill_session(token)


_COVERAGE_MAX_MEDIA = 256


async def advance_prompt_coverage(
    chat_id: int, user_id: int, update: state.PromptCoverage
) -> None:
    """Merge one turn's delivered content into the conversation coverage cursor.

    Called only after the run's history was persisted, so a failed turn
    leaves the cursor untouched and the next turn re-sends its prompt fully.
    """
    key = state.prompt_coverage_key(chat_id, user_id)
    cov = await memttlcache.get(key)
    if cov is None:
        cov = state.PromptCoverage()
    cov.last_message_id = max(cov.last_message_id, update.last_message_id)
    for unique, number in update.sent_media.items():
        cov.sent_media[unique] = number
    new_max = max(update.sent_media.values(), default=0)
    cov.next_number = max(cov.next_number, new_max + 1)
    if len(cov.sent_media) > _COVERAGE_MAX_MEDIA:
        # keep only this turn's media: recency beats completeness
        cov.sent_media = dict(update.sent_media)
    await memttlcache.set(key, cov, ttl=app_config.cachettl_agent_history)


async def _stop_typing_keepalive(
    typing_keepalive: TypingKeepAlive | None,
) -> None:
    """Stop a caller-owned typing task without masking the agent outcome."""
    if typing_keepalive is None:
        return
    stop = getattr(typing_keepalive, "stop", None)
    if stop is None:
        return
    try:
        await stop()
    except Exception as e:
        logger.debug(f"Failed to stop typing keepalive: {e.__class__.__name__} - {e}")


async def run_agent(
    agi: Agent[Any, Any],
    client: PyrogramClient,
    message: pyrogram.types.Message,
    user_id: int,
    chat_id: int,
    user_prompt: list[UserContent],
    history: list[ModelMessage],
    deps: Any,
    multimodal_model: Any,
    model: Any,
    lang: str,
    additional_instructions: str | None = None,
    typing_keepalive: TypingKeepAlive | None = None,
    coverage_meta: state.PromptCoverage | None = None,
) -> None:
    """Run the agent with an overall wall-clock timeout guard.

    ``typing_keepalive`` is normally started by the caller before context
    collection. The runner owns cleanup on every exit, including cancellation,
    timeout, and model errors, so an error reply cannot leave a live indicator.
    """
    timeout = app_config.agent_run_timeout
    coro = _run_agent_impl(
        agi=agi,
        client=client,
        message=message,
        user_id=user_id,
        chat_id=chat_id,
        user_prompt=user_prompt,
        history=history,
        deps=deps,
        multimodal_model=multimodal_model,
        model=model,
        lang=lang,
        additional_instructions=additional_instructions,
        typing_keepalive=typing_keepalive,
        coverage_meta=coverage_meta,
    )
    try:
        if not timeout or timeout <= 0:
            await coro
            return
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            await _stop_typing_keepalive(typing_keepalive)
            logger.warning(
                f"Agent run timed out after {timeout}s for user {user_id} in chat {chat_id}"
            )
            try:
                err_text = i18n.t(
                    "bot.msg.agent.errors.interrupted", locale=lang
                ).format(error="Timeout")
                if deps.is_guest_mode:
                    await reply_output(client, message, err_text, deps=deps)
                else:
                    await message.reply_text(err_text)
            except Exception as e:
                logger.error(
                    f"Failed to send timeout notice: {e.__class__.__name__} - {e}"
                )
    finally:
        await _stop_typing_keepalive(typing_keepalive)


async def _run_agent_impl(
    agi: Agent[Any, Any],
    client: PyrogramClient,
    message: pyrogram.types.Message,
    user_id: int,
    chat_id: int,
    user_prompt: list[UserContent],
    history: list[ModelMessage],
    deps: Any,
    multimodal_model: Any,
    model: Any,
    lang: str,
    additional_instructions: str | None = None,
    typing_keepalive: TypingKeepAlive | None = None,
    coverage_meta: state.PromptCoverage | None = None,
) -> None:
    """Run the agent with full streaming/non-streaming support, history saving,
    TypingKeepAlive and unified error handling.

    This is the single source of truth for agent execution shared by both
    the normal wake flow and the follow-up flow.
    """

    is_guest_mode = deps.is_guest_mode

    if not is_chat_allowed(chat_id):
        return

    needs_multimodal = check_needs_multimodal(user_prompt, history)

    override_name = await get_chat_model_override(chat_id, "main")
    multimodal_override = await get_chat_model_override(chat_id, "multimodal")
    effective_multimodal = (
        provider.make_chat_model(multimodal_override)
        if multimodal_override
        else multimodal_model
    )
    if app_config.agent_multimodal_mode == "transcribe":
        if needs_multimodal:
            sanitized_history = await transcribe_multimodal_history(
                effective_multimodal, history
            )
            if sanitized_history is not history:
                history = sanitized_history
                deps.history = history
                # Persist the migration even when the main model later fails;
                # otherwise the same binary would be retried on every turn.
                try:
                    await memttlcache.set(
                        state.history_key(chat_id, user_id),
                        history,
                        ttl=app_config.cachettl_agent_history,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to cache sanitized agent history: "
                        f"{e.__class__.__name__} - {e}"
                    )
            user_prompt = await transcribe_multimodal_content(
                effective_multimodal, user_prompt
            )
        # A text-model run must never receive historical or current media,
        # including when the transcription provider is unavailable.
        needs_multimodal = False
    if override_name:
        if needs_multimodal and effective_multimodal:
            use_model = effective_multimodal
        else:
            use_model = provider.make_chat_model(override_name)
    else:
        use_model = effective_multimodal if needs_multimodal else model

    # Pair the per-model config options with the model actually used. Override
    # models (per-chat /command) have no options of their own and fall back to
    # the main model's settings.
    if use_model is effective_multimodal:
        model_settings = provider.make_model_settings(
            app_config.agent_model_multimodal_options
        )
    else:
        model_settings = provider.make_model_settings(app_config.agent_model_options)

    try:
        ctx = typing_keepalive
        ctx_owned = ctx is None
        if ctx is None and not is_guest_mode:
            ctx = TypingKeepAlive(client, message)
            await ctx.__aenter__()
        try:
            if app_config.agent_streaming and not is_guest_mode:
                streaming_output: StreamingOutput | None = None
                output: Any = None
                try:
                    async with _iter_with_spill_session(
                        agi,
                        chat_id=chat_id,
                        user_id=user_id,
                        model=use_model,
                        model_settings=model_settings,
                        instructions=additional_instructions,
                        user_prompt=user_prompt,
                        message_history=history,
                        deps=deps,
                        usage_limits=safety.build_usage_limits(),
                    ) as agent_run:
                        node = agent_run.next_node
                        while not Agent.is_end_node(node):
                            if Agent.is_model_request_node(node):
                                async with node.stream(agent_run.ctx) as request_stream:
                                    async for event in request_stream:
                                        if isinstance(event, PartStartEvent):
                                            if isinstance(event.part, TextPart):
                                                if streaming_output is None:
                                                    streaming_output = StreamingOutput(
                                                        client, message, deps=deps
                                                    )
                                                await streaming_output.append_delta(
                                                    event.part.content
                                                )
                                        elif isinstance(event, PartDeltaEvent):
                                            if isinstance(event.delta, TextPartDelta):
                                                if streaming_output is None:
                                                    streaming_output = StreamingOutput(
                                                        client, message, deps=deps
                                                    )
                                                await streaming_output.append_delta(
                                                    event.delta.content_delta
                                                )
                            elif Agent.is_call_tools_node(node):
                                has_tool_calls = any(
                                    part.part_kind == "tool-call"
                                    for part in node.model_response.parts
                                )
                                if has_tool_calls and streaming_output is not None:
                                    await streaming_output.finalize()
                                    streaming_output = None
                            # next() runs the full capability lifecycle
                            # (before/wrap/after_node_run), which drains
                            # end-of-run pending messages into a redirect
                            # instead of stranding them.
                            node = await agent_run.next(node)
                        assert agent_run.result is not None, (
                            "Agent run ended without result"
                        )
                        logger.debug(
                            f"Agent run end with result: {agent_run.result.output}"
                        )
                        output = agent_run.result.output
                        if isinstance(output, (EndTurn, AskUserOutput)):
                            if streaming_output is not None:
                                await streaming_output.abort()
                        else:
                            # Check final_result first before sending anything
                            if isinstance(output, str) and "final_result" in output:
                                if streaming_output is not None:
                                    await streaming_output.abort()
                                logger.warning(
                                    f"The stupid agent returned 'final_result' as text🤡 for user {user_id}"
                                )
                            elif streaming_output is not None:
                                await streaming_output.finalize()
                            elif output:
                                await reply_output(client, message, output, deps=deps)
                        # Save full output for follow-up detection
                        full_output = ""
                        if streaming_output is not None:
                            full_output = streaming_output.current_text
                        elif isinstance(output, str):
                            full_output = output
                        if (
                            full_output
                            and message.chat
                            and message.chat.type
                            in (
                                pyrogram.enums.ChatType.SUPERGROUP,
                                pyrogram.enums.ChatType.GROUP,
                            )
                        ):
                            # Get last reply info from existing BotLastReply if available
                            bot_reply = await memttlcache.get(
                                state.bot_last_reply_key(chat_id)
                            )
                            if bot_reply and isinstance(
                                bot_reply, datatype.BotLastReply
                            ):
                                bot_reply.full_output = full_output
                                await memttlcache.set(
                                    state.bot_last_reply_key(chat_id),
                                    bot_reply,
                                    ttl=300,
                                )
                        await memttlcache.set(
                            state.history_key(chat_id, user_id),
                            agent_run.all_messages(),
                            ttl=app_config.cachettl_agent_history,
                        )
                        if not is_guest_mode and coverage_meta is not None:
                            await advance_prompt_coverage(
                                chat_id, user_id, coverage_meta
                            )
                        log_run_cache_stats(use_model.model_name, agent_run.usage)
                except Exception:
                    if streaming_output is not None:
                        await streaming_output.abort()
                    raise
            else:
                async with _iter_with_spill_session(
                    agi,
                    chat_id=chat_id,
                    user_id=user_id,
                    model=use_model,
                    model_settings=model_settings,
                    user_prompt=user_prompt,
                    instructions=additional_instructions,
                    message_history=history,
                    deps=deps,
                    usage_limits=safety.build_usage_limits(),
                ) as agent_run:
                    replied = False
                    full_output_parts: list[str] = []
                    output: Any = None
                    node = agent_run.next_node
                    while not Agent.is_end_node(node):
                        if Agent.is_call_tools_node(node):
                            for part in node.model_response.parts:
                                if part.part_kind == "text" and part.content:
                                    # Check if content is final_result before sending
                                    if "final_result" in part.content:
                                        logger.warning(
                                            f"The stupid agent returned 'final_result' as text🤡 for user {user_id}"
                                        )
                                    else:
                                        if not is_guest_mode:
                                            await reply_output(
                                                client, message, part.content
                                            )
                                        full_output_parts.append(part.content)
                                        replied = True
                        # next() runs the full capability lifecycle, which
                        # drains end-of-run pending messages into a redirect.
                        node = await agent_run.next(node)
                    assert agent_run.result is not None, (
                        "Agent run ended without result"
                    )
                    logger.info(f"Agent run end for user {user_id} in chat {chat_id}")
                    logger.debug(
                        f"Agent run end with result: {agent_run.result.output}"
                    )
                    output = agent_run.result.output
                    if isinstance(output, str) and "final_result" in output:
                        logger.warning(
                            f"The stupid agent returned 'final_result' as text🤡 for user {user_id}"
                        )
                    elif isinstance(output, (EndTurn, AskUserOutput)):
                        logger.debug(
                            f"Agent returned {type(output).__name__} for user {user_id}"
                        )
                    elif not replied and output:
                        if not is_guest_mode:
                            await reply_output(client, message, output)
                        full_output_parts.append(output)
                    # In guest mode, send a single collected reply at the end
                    if is_guest_mode and full_output_parts:
                        full_text = "\n".join(full_output_parts)
                        await reply_output(client, message, full_text, deps=deps)
                    # Save full output for follow-up detection
                    full_output = "\n".join(full_output_parts)
                    if (
                        full_output
                        and message.chat
                        and message.chat.type
                        in (
                            pyrogram.enums.ChatType.SUPERGROUP,
                            pyrogram.enums.ChatType.GROUP,
                        )
                    ):
                        bot_reply = await memttlcache.get(
                            state.bot_last_reply_key(chat_id)
                        )
                        if bot_reply and isinstance(bot_reply, datatype.BotLastReply):
                            bot_reply.full_output = full_output
                            await memttlcache.set(
                                state.bot_last_reply_key(chat_id),
                                bot_reply,
                                ttl=300,
                            )
                    await memttlcache.set(
                        state.history_key(chat_id, user_id),
                        agent_run.all_messages(),
                        ttl=app_config.cachettl_agent_history,
                    )
                    if not is_guest_mode and coverage_meta is not None:
                        await advance_prompt_coverage(chat_id, user_id, coverage_meta)
                    log_run_cache_stats(use_model.model_name, agent_run.usage)
        finally:
            if ctx is not None and ctx_owned:
                await ctx.__aexit__(None, None, None)
    except TypeError as e:
        await _stop_typing_keepalive(typing_keepalive)
        # https://github.com/pydantic/pydantic-ai/issues/527
        # https://github.com/pydantic/pydantic-ai/issues/1813
        # https://github.com/pydantic/pydantic-ai/issues/1746
        logger.exception(f"Agent run error: {e}")
        err_text = i18n.t("bot.msg.agent.errors.too_fast", locale=lang)
        if is_guest_mode:
            await reply_output(client, message, err_text, deps=deps)
        else:
            await message.reply_text(err_text)
    except (
        pydantic_ai.exceptions.ModelHTTPError,
        pydantic_ai.exceptions.ModelAPIError,
    ) as e:
        await _stop_typing_keepalive(typing_keepalive)
        logger.error(f"Agent HTTP error: {e.__class__.__name__}: {e}")
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=i18n.t("bot.button.agent.clear_history", locale=lang),
                        callback_data=f"agent_clear_history:{chat_id}:{user_id}",
                    )
                ]
            ]
        )
        status_code = getattr(e, "status_code", None)
        if is_guest_mode:
            base = i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
                error="Error"
            )
            await reply_output(client, message, base, deps=deps)
        elif status_code == 400:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.model_http_400", locale=lang),
                reply_markup=markup,
            )
        elif status_code:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.model_http", locale=lang).format(
                    code=status_code
                ),
            )
        else:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
                    error="Error"
                ),
                reply_markup=markup,
            )
    except Exception as e:
        await _stop_typing_keepalive(typing_keepalive)
        logger.error(f"Agent run error: {e.__class__.__name__} - {e}")
        err_text = i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
            error="Error"
        )
        if is_guest_mode:
            await reply_output(client, message, err_text, deps=deps)
        else:
            await message.reply_text(err_text)
