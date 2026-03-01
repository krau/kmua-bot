from typing import Any

import pydantic_ai
import pyrogram
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    UserContent,
)
from pydantic_ai.messages import (
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram.client import Client as PyrogramClient

from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.agent import state
from kmua.plugins.agent.output import StreamingOutput, TypingKeepAlive, reply_output
from kmua.plugins.agent.prompt import check_needs_multimodal


def _make_model(model_name: str) -> OpenAIChatModel:
    """Construct an OpenAIChatModel using the global provider settings."""
    return OpenAIChatModel(
        model_name=model_name,
        provider=OpenAIProvider(
            base_url=app_config.agent_provider_url,
            api_key=app_config.agent_api_key,
        ),
    )


async def get_chat_model_override(chat_id: int) -> str | None:
    """Return the per-chat model override name, or None if not set."""
    return await memttlcache.get(state.chat_model_override_key(chat_id))


async def set_chat_model_override(chat_id: int, model_name: str | None) -> None:
    """Set (or clear) the per-chat model override.

    Pass model_name=None to reset to the global default.
    Stored without TTL so it persists until the bot restarts.
    """
    key = state.chat_model_override_key(chat_id)
    if model_name is None:
        await memttlcache.delete(key)
    else:
        # No TTL — intentionally lives until restart
        await memttlcache.set(key, model_name)


async def run_agent(
    agent_instance: Any,
    client: PyrogramClient,
    message: pyrogram.types.Message,
    user_id: int,
    chat_id: int,
    instructions: str,
    user_prompt: list[UserContent],
    history: list[ModelMessage],
    deps: Any,
    multimodal_model: Any,
    model: Any,
    lang: str,
) -> None:
    """Run the agent with full streaming/non-streaming support, history saving,
    TypingKeepAlive and unified error handling.

    This is the single source of truth for agent execution shared by both
    the normal wake flow and the follow-up flow.
    """
    from kmua.plugins.agent import tools

    needs_multimodal = check_needs_multimodal(user_prompt, history)

    # Apply per-chat model override if set
    override_name = await get_chat_model_override(chat_id)
    if override_name:
        use_model = _make_model(override_name)
    else:
        use_model = multimodal_model if needs_multimodal else model

    try:
        async with TypingKeepAlive(client, message):
            if app_config.agent_streaming:
                streaming_output: StreamingOutput | None = None
                try:
                    async with agent_instance.iter(
                        instructions=instructions,
                        model=use_model,
                        user_prompt=user_prompt,
                        message_history=history,
                        deps=deps,
                    ) as agent_run:
                        async for node in agent_run:
                            if Agent.is_model_request_node(node):
                                async with node.stream(agent_run.ctx) as request_stream:
                                    async for event in request_stream:
                                        if isinstance(event, PartStartEvent):
                                            if isinstance(event.part, TextPart):
                                                if streaming_output is None:
                                                    streaming_output = StreamingOutput(
                                                        client, message
                                                    )
                                                await streaming_output.append_delta(
                                                    event.part.content
                                                )
                                        elif isinstance(event, PartDeltaEvent):
                                            if isinstance(event.delta, TextPartDelta):
                                                if streaming_output is None:
                                                    streaming_output = StreamingOutput(
                                                        client, message
                                                    )
                                                await streaming_output.append_delta(
                                                    event.delta.content_delta
                                                )
                            elif Agent.is_call_tools_node(node):
                                has_tool_calls = False
                                for part in node.model_response.parts:
                                    if part.part_kind == "tool-call":
                                        has_tool_calls = True
                                        args_str = str(part.args) if part.args else ""
                                        logger.debug(
                                            f"Tool call for user {user_id} in chat {chat_id}: "
                                            f"{part.tool_name}({args_str[:200]}...)"
                                        )
                                if has_tool_calls and streaming_output is not None:
                                    await streaming_output.finalize()
                                    streaming_output = None
                            elif Agent.is_end_node(node):
                                assert agent_run.result is not None, (
                                    "Agent run ended without result"
                                )
                                logger.debug(
                                    f"Agent run end with result: {agent_run.result.output}"
                                )
                                output = agent_run.result.output
                                if isinstance(output, DeferredToolRequests):
                                    if streaming_output is not None:
                                        await streaming_output.abort()
                                    logger.info(
                                        f"Agent returned DeferredToolRequests for user {user_id}"
                                    )
                                    await tools.update_ask_history(
                                        chat_id, user_id, agent_run.all_messages()
                                    )
                                else:
                                    if streaming_output is not None:
                                        await streaming_output.finalize()
                                    elif output:
                                        await reply_output(client, message, output)
                        await memttlcache.set(
                            state.history_key(chat_id, user_id),
                            agent_run.all_messages(),
                            ttl=app_config.cachettl_agent_history,
                        )
                except Exception:
                    if streaming_output is not None:
                        await streaming_output.abort()
                    raise
            else:
                async with agent_instance.iter(
                    instructions=instructions,
                    model=use_model,
                    user_prompt=user_prompt,
                    message_history=history,
                    deps=deps,
                ) as agent_run:
                    replied = False
                    async for node in agent_run:
                        if Agent.is_call_tools_node(node):
                            for part in node.model_response.parts:
                                if part.part_kind == "tool-call":
                                    args_str = str(part.args) if part.args else ""
                                    logger.debug(
                                        f"Tool call: {part.tool_name}"
                                        f"({args_str[:200]}{'...' if len(args_str) > 200 else ''})"
                                    )
                                elif part.part_kind == "text" and part.content:
                                    await reply_output(client, message, part.content)
                                    replied = True
                        elif Agent.is_end_node(node):
                            assert agent_run.result is not None, (
                                "Agent run ended without result"
                            )
                            logger.debug(
                                f"Agent run end with result: {agent_run.result.output}"
                            )
                            output = agent_run.result.output
                            if isinstance(output, DeferredToolRequests):
                                logger.info(
                                    f"Agent returned DeferredToolRequests for user {user_id}"
                                )
                            elif not replied and output:
                                await reply_output(client, message, output)
                    await memttlcache.set(
                        state.history_key(chat_id, user_id),
                        agent_run.all_messages(),
                        ttl=app_config.cachettl_agent_history,
                    )
    except TypeError as e:
        # https://github.com/pydantic/pydantic-ai/issues/527
        # https://github.com/pydantic/pydantic-ai/issues/1813
        # https://github.com/pydantic/pydantic-ai/issues/1746
        logger.exception(f"Agent run error: {e}")
        await message.reply_text(
            f"{i18n.t('bot.msg.agent.errors.too_fast', locale=lang)}\n<code>{e}</code>",
            parse_mode=pyrogram.enums.ParseMode.HTML,
        )
    except (
        pydantic_ai.exceptions.ModelHTTPError,
        pydantic_ai.exceptions.ModelAPIError,
    ) as e:
        logger.error(f"Agent HTTP error: {e.__class__.__name__}: {e}")
        status_code = getattr(e, "status_code", None)
        if status_code == 400:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.model_http_400", locale=lang)
            )
        elif status_code:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.model_http", locale=lang).format(
                    code=status_code
                )
            )
        else:
            await message.reply_text(
                i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
                    error=f"{e.__class__.__name__}"
                )
            )
    except Exception as e:
        logger.error(f"Agent run error: {e.__class__.__name__} - {e}")
        await message.reply_text(
            i18n.t("bot.msg.agent.errors.interrupted", locale=lang).format(
                error=f"{e.__class__.__name__}"
            )
        )
