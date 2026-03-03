import asyncio

import pyrogram
from ddgs import DDGS
from powermem import AsyncMemory
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    ModelMessage,
    RunContext,
    Tool,
)
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import manyacg

from . import datatype, myfilter, provider, state, tools, utils
from .history import (
    get_history_text,
    should_compress_by_tokens,
    summarize_history,
    truncate_multimodal,
)
from .prompt import build_ctx_info, get_input_prompt
from .runner import (
    get_chat_model_override,
    get_chat_prompt_override,
    run_agent,
    set_chat_model_override,
    set_chat_prompt_override,
)
from .simple_reply import word_reply

agent = None
model = None
small_model = None
multimodal_model = None
summary_agent = None
memory_agent = None
powermemory = None

if app_config.agent_powermem_config is not None:
    # for group memory, the key is f"group_{chat_id}"
    powermemory = AsyncMemory(app_config.agent_powermem_config)

    async def _init_powermem():
        assert powermemory is not None
        await powermemory.initialize()

    asyncio.create_task(_init_powermem())


async def history_processor(
    ctx: RunContext[datatype.ContextDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    assert summary_agent is not None, "summary_agent is not initialized"
    assert memory_agent is not None, "memory_agent is not initialized"
    summary = await summarize_history(summary_agent, messages)
    if app_config.agent_multimodal_max_items > 0:
        summary = truncate_multimodal(summary, app_config.agent_multimodal_max_items)
    await common.memttlcache.set(
        state.history_key(ctx.deps.chat_id, ctx.deps.user_id),
        summary,
        ttl=app_config.cachettl_agent_history,
    )
    should_update_memory = (
        should_compress_by_tokens(messages)
        if app_config.agent_context_window_tokens
        else len(messages) >= app_config.agent_messages_threshold
    )
    if should_update_memory:
        try:
            history_text = get_history_text(messages)
            await utils.update_user_memory(memory_agent, history_text, ctx.deps.user_id)
        except Exception as e:
            logger.exception(
                f"Error updating memory for user {ctx.deps.user_id}: {e.__class__.__name__} - {e}"
            )
    return summary


if app_config.agent:
    model = provider.make_chat_model(app_config.agent_model)
    multimodal_model = (
        model
        if not app_config.agent_model_multimodal
        else provider.make_chat_model(app_config.agent_model_multimodal)
    )
    small_model = (
        model
        if not app_config.agent_model_small
        else provider.make_chat_model(app_config.agent_model_small)
    )
    agent = Agent(
        model=model,
        # instructions=app_config.agent_prompt,
        output_type=[str, DeferredToolRequests],
        tools=[
            Tool(tools.get_chat_info, prepare=tools.prepare_group_tools),
            Tool(tools.get_history_messages, prepare=tools.prepare_group_tools),
            Tool(
                DuckDuckGoSearchTool(DDGS(), max_results=3).__call__,
                name="duckduckgo_search",
                description="Searches DuckDuckGo for the given query and returns the results.",
                prepare=tools.prepare_configurable_tools,
            ),
            Tool(
                tools.search_messages,
                prepare=tools.prepare_message_search_tool,
            ),
            Tool(
                tools.send_chat_quote,
                prepare=tools.prepare_group_tools,
            ),
            Tool(
                tools.search_group_memory,
                prepare=tools.prepare_powermem_tool,
            ),
            Tool(
                tools.update_group_memory,
                prepare=tools.prepare_powermem_tool,
            ),
            Tool(
                tools.generate_image,
                prepare=tools.prepare_image_gen_tools,
            ),
            Tool(
                tools.edit_image,
                prepare=tools.prepare_image_edit_tools,
            ),
            Tool(
                tools.webfetch,
                prepare=tools.prepare_configurable_tools,
            ),
            Tool(
                tools.send_sticker,
                prepare=tools.prepare_periodic_sticker,
                sequential=True,
            ),
            Tool(tools.ask_user, sequential=True),
            Tool(tools.send_anime_photo, sequential=True),
            Tool(
                tools.send_reaction,
                prepare=tools.prepare_periodic_reaction,
            ),
            Tool(tools.send_media, sequential=True),
            Tool(tools.send_poll, sequential=True),
            Tool(tools.send_text, sequential=True),
        ],
        deps_type=datatype.ContextDeps,
        history_processors=[history_processor],
        retries=5,
    )

    @agent.instructions
    async def _dynamic_instructions(ctx: RunContext[datatype.ContextDeps]) -> str:
        return ctx.deps.instructions

    tools.set_agent(agent, model=model, multimodal_model=multimodal_model)
    summary_agent = Agent(model=model, instructions=app_config.agent_summary_prompt)
    memory_agent = Agent(
        model=model,
        output_type=datatype.UserMemoryResult,
        instructions=app_config.agent_memory_prompt,
    )

    @PyrogramClient.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: PyrogramClient, message: pyrogram.types.Message):
        user = message.sender_chat or message.from_user
        if not user or user.id is None:
            return
        user_config = await database.get_user_config(user.id)
        if await common.memstore.get(state.waiting_key(user.id)):
            await message.reply_text(
                i18n.t("bot.msg.agent.waiting", locale=user_config.lang)
            )
            return
        chat_id = message.chat.id if message.chat else user.id
        if not chat_id:
            return
        await common.memttlcache.delete(state.history_key(chat_id, user.id))
        await tools.clear_ask_state(chat_id, user.id)
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )

    @PyrogramClient.on_callback_query(
        pyrogram.filters.regex(r"^agent_clear_history:(-?\d+):(\d+)$"), group=0
    )
    async def on_clear_history_callback(
        client: PyrogramClient, callback_query: pyrogram.types.CallbackQuery
    ):
        data = str(callback_query.data)
        parts = data.split(":")
        target_chat_id = int(parts[1])
        target_user_id = int(parts[2])

        caller = callback_query.from_user
        if not caller or caller.id != target_user_id:
            await callback_query.answer(show_alert=True)
            return

        user_config = await database.get_user_config(caller.id)
        lang = user_config.lang

        await common.memttlcache.delete(
            state.history_key(target_chat_id, target_user_id)
        )
        await tools.clear_ask_state(target_chat_id, target_user_id)

        await callback_query.answer(
            i18n.t("bot.msg.agent.forgot", locale=lang), show_alert=False
        )
        if callback_query.message:
            await callback_query.message.edit_reply_markup(reply_markup=None)  # type: ignore

    @PyrogramClient.on_message(pyrogram.filters.command("model"), group=0)
    async def set_model_command(
        client: PyrogramClient, message: pyrogram.types.Message
    ):
        user = message.from_user
        if not user or not user.id:
            return
        db_user = await database.get_user_by_id(user.id)
        if not db_user:
            return
        if not db_user.is_bot_global_admin and user.id not in app_config.owners:
            return
        chat_id = message.chat.id if message.chat else None
        if not chat_id:
            return
        args = message.text.split(maxsplit=2) if message.text else []

        # Subcommand dispatch: /model [main|multimodal|small] [model_spec]
        # /model                  → show current overrides
        # /model <spec>           → set main model (backward compat)
        # /model main [spec]      → set/reset main model
        # /model multimodal [spec]→ set/reset multimodal model
        # /model small [spec]     → set/reset small model

        SUBCOMMANDS = {"main", "multimodal", "small"}

        subcommand: str | None = None
        model_name: str | None = None

        if len(args) == 1:
            # /model  → show current overrides
            subcommand = None
            model_name = None
        elif len(args) == 2:
            arg1 = args[1].strip()
            if arg1 in SUBCOMMANDS:
                # /model main  /model multimodal  /model small  → reset that model
                subcommand = arg1
                model_name = None
            else:
                # /model <spec>  → backward-compat: set main model
                subcommand = "main"
                model_name = arg1
        else:
            # len >= 3
            arg1 = args[1].strip()
            if arg1 in SUBCOMMANDS:
                subcommand = arg1
                model_name = args[2].strip()
            else:
                # Unrecognised, treat whole remainder as main model spec
                subcommand = "main"
                model_name = " ".join(args[1:]).strip()

        # --- No subcommand: show current state ---
        if subcommand is None:
            cur_main = await get_chat_model_override(chat_id, "main")
            cur_mm = await get_chat_model_override(chat_id, "multimodal")
            cur_small = await get_chat_model_override(chat_id, "small")
            lines = [
                "<b>Current model overrides for this chat:</b>",
                f"  main:       <code>{cur_main or '(global default: ' + app_config.agent_model + ')'}</code>",
                f"  multimodal: <code>{cur_mm or '(global default: ' + (app_config.agent_model_multimodal or app_config.agent_model) + ')'}</code>",
                f"  small:      <code>{cur_small or '(global default: ' + (app_config.agent_model_small or app_config.agent_model) + ')'}</code>",
                "",
                "Usage: <code>/model [main|multimodal|small] [model_spec]</code>",
                "Omit model_spec to reset to global default.",
            ]
            await message.reply_text(
                "\n".join(lines),
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            return

        # --- Handle main model ---
        if subcommand == "main":
            current = await get_chat_model_override(chat_id, "main")
            if model_name:
                await set_chat_model_override(chat_id, model_name, "main")
                prev = current or app_config.agent_model
                await message.reply_text(
                    f"Main model for this chat set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set main model override for chat {chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(chat_id, None, "main")
                prev = current or app_config.agent_model
                await message.reply_text(
                    f"Main model for this chat reset to global default "
                    f"<code>{app_config.agent_model}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset main model override for chat {chat_id} "
                    f"(was: {current!r})"
                )

        # --- Handle multimodal model ---
        elif subcommand == "multimodal":
            current = await get_chat_model_override(chat_id, "multimodal")
            global_default = app_config.agent_model_multimodal or app_config.agent_model
            if model_name:
                await set_chat_model_override(chat_id, model_name, "multimodal")
                prev = current or global_default
                await message.reply_text(
                    f"Multimodal model for this chat set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set multimodal model override for chat {chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(chat_id, None, "multimodal")
                prev = current or global_default
                await message.reply_text(
                    f"Multimodal model for this chat reset to global default "
                    f"<code>{global_default}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset multimodal model override for chat {chat_id} "
                    f"(was: {current!r})"
                )

        # --- Handle small model ---
        elif subcommand == "small":
            current = await get_chat_model_override(chat_id, "small")
            global_default = app_config.agent_model_small or app_config.agent_model
            if model_name:
                await set_chat_model_override(chat_id, model_name, "small")
                prev = current or global_default
                await message.reply_text(
                    f"Small model for this chat set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set small model override for chat {chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(chat_id, None, "small")
                prev = current or global_default
                await message.reply_text(
                    f"Small model for this chat reset to global default "
                    f"<code>{global_default}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset small model override for chat {chat_id} "
                    f"(was: {current!r})"
                )

    @PyrogramClient.on_message(pyrogram.filters.command("prompt"), group=0)
    async def set_prompt_command(
        client: PyrogramClient, message: pyrogram.types.Message
    ):
        user = message.from_user
        if not user or not user.id:
            return
        db_user = await database.get_user_by_id(user.id)
        if not db_user:
            return
        if not db_user.is_bot_global_admin and user.id not in app_config.owners:
            return
        chat_id = message.chat.id if message.chat else None
        if not chat_id:
            return

        # Split only on the first whitespace to capture the full prompt text
        args = message.text.split(maxsplit=1) if message.text else []
        prompt_text = args[1].strip() if len(args) >= 2 else None

        current = await get_chat_prompt_override(chat_id)

        if prompt_text is None:
            # /prompt — show status
            if current:
                status = "Custom prompt is <b>active</b> for this chat."
            else:
                status = "Using <b>default</b> prompt for this chat."
            await message.reply_text(
                f"{status}\n\nUsage:\n"
                "<code>/prompt &lt;text&gt;</code> — set custom prompt\n"
                "<code>/prompt reset</code> — restore default",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        elif prompt_text.lower() == "reset":
            # /prompt reset — clear override
            await set_chat_prompt_override(chat_id, None)
            await message.reply_text(
                "Prompt for this chat reset to default.",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            logger.info(
                f"Admin {user.id} reset prompt override for chat {chat_id} "
                f"(had custom: {current is not None})"
            )
        else:
            # /prompt <text> — set override
            await set_chat_prompt_override(chat_id, prompt_text)
            await message.reply_text(
                "Custom prompt set for this chat.",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            logger.info(
                f"Admin {user.id} set prompt override for chat {chat_id} "
                f"(replaced existing: {current is not None})"
            )


_filter = (
    myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter)
    & myfilter.not_bottle_reply_filter
    & ~pyrogram.filters.regex("|".join([r.pattern for r in manyacg.ARTWORK_ALL_REGEX]))
)


@PyrogramClient.on_message(_filter, group=0)
async def wake_agent(client: PyrogramClient, message: pyrogram.types.Message):
    # some check
    if not agent:
        return await word_reply(client, message)
    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return await word_reply(client, message)
    chat = message.chat
    if not chat or not chat.id:
        return await word_reply(client, message)
    if (
        app_config.agent_whitelist_mode
        and user.id not in app_config.agent_whitelist
        and chat.id not in app_config.agent_whitelist
    ):
        return await word_reply(client, message)
    if chat.type == pyrogram.enums.ChatType.SUPERGROUP:
        chat_config = await database.get_chat_config(chat)
        if not chat_config.ai_reply:
            return await word_reply(client, message)
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    if await common.memstore.get(state.waiting_key(user.id)):
        return await word_reply(client, message)

    # Check if there's a pending deferred ask
    ask_state = await tools.get_ask_state(chat.id, user.id)
    if ask_state is not None:
        # Resume the deferred ask with "no answer" result
        # Include the new user message so agent can see it (with multimodal support)
        user_prompt, needs_multimodal = await get_input_prompt(
            client, message, include_nearby=0, ctx=None
        )
        user_message_text = message.text or message.caption or ""
        logger.info(
            f"Resuming deferred ask for user {user.id} with no answer, "
            f"user_message='{user_message_text[:50]}...', needs_multimodal={needs_multimodal}"
        )
        await tools.resume_ask(
            client=client,
            ask_state=ask_state,
            answer="用户没有回答，而是发送了新消息",
            message=message,
            powermemory=powermemory,
            user_prompt=user_prompt,
            needs_multimodal=needs_multimodal,
        )
        return

    await common.memstore.set(state.waiting_key(user.id), True)
    # set language
    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user.id)).lang
    else:
        lang = (await database.get_chat_config(chat.id)).lang

    # agent run
    try:
        chat_id = chat.id
        history: list[ModelMessage] = await common.memttlcache.get(
            state.history_key(chat_id, user.id), []
        )
        is_group_chat = chat.type in (
            pyrogram.enums.ChatType.SUPERGROUP,
            pyrogram.enums.ChatType.GROUP,
        )
        instructions = (
            app_config.agent_prompt
            if not is_group_chat
            else app_config.agent_group_prompt
            if app_config.agent_group_prompt
            else app_config.agent_prompt
        )
        prompt_override = await get_chat_prompt_override(chat_id)
        if prompt_override:
            instructions = prompt_override
        ctx_info = await build_ctx_info(
            message=message,
            user=user,
            user_data=user_data,
            history=history,
            is_group_chat=is_group_chat,
        )
        # 在群聊场景中获取附近消息作为上下文
        # [TODO] 好像自动添加附近消息反而效果不好了
        nearby_count = (
            app_config.agent_group_context_nearby_message_count if is_group_chat else 0
        )
        user_prompt, _ = await get_input_prompt(
            client, message, include_nearby=nearby_count, ctx=None
        )
        user_message_text = message.text or message.caption or ""
        if user_message_text:
            logger.debug(
                f"User {user.id} wake agent in Chat {chat.id}: {user_message_text}"
            )
        await utils.cache_user_image(message, chat_id, user.id)
        await run_agent(
            agi=agent,
            additional_instructions=ctx_info.to_text() if ctx_info else None,
            client=client,
            message=message,
            user_id=user.id,
            chat_id=chat_id,
            user_prompt=user_prompt,
            history=history,
            deps=datatype.ContextDeps(
                user_id=user.id,
                chat_id=chat_id,
                message=message,
                client=client,
                instructions=instructions,
                powermemory=powermemory,
                history=history,
            ),  # type: ignore
            multimodal_model=multimodal_model,
            model=model,
            lang=lang,
        )
        # Increment periodic counters after each completed conversation turn.
        if app_config.agent_periodic_sticker_interval > 0:
            sticker_ctr: int = await common.memstore.get(
                state.periodic_sticker_counter_key(chat_id, user.id), 0
            )
            await common.memstore.set(
                state.periodic_sticker_counter_key(chat_id, user.id), sticker_ctr + 1
            )
        if app_config.agent_periodic_reaction_interval > 0:
            reaction_ctr: int = await common.memstore.get(
                state.periodic_reaction_counter_key(chat_id, user.id), 0
            )
            await common.memstore.set(
                state.periodic_reaction_counter_key(chat_id, user.id),
                reaction_ctr + 1,
            )
    finally:
        await common.memstore.delete(state.waiting_key(user.id))
