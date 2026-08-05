import asyncio
import random

import pyrogram
from powermem import AsyncMemory
from pydantic_ai import (
    Agent,
    ModelMessage,
    RunContext,
    Tool,
)
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import link_parse, manyacg

from . import datatype, myfilter, provider, runner, safety, state, tools, utils
from .history import compact_history
from .prompt import build_ctx_info, get_input_prompt
from .runner import (
    get_chat_model_override,
    get_chat_prompt_override,
    run_agent,
    set_chat_model_override,
    set_chat_prompt_override,
)
from .simple_reply import word_reply
from .whitelist import is_chat_allowed

agent = None
model = None
small_model = None
multimodal_model = None
struct_model = None
memory_agent: Agent[None, datatype.UserMemoryResult] | None = None
powermemory = None
# Becomes True only after AsyncMemory.initialize() succeeds. The powermem
# tools are gated on this so a failed/slow init degrades gracefully (the
# tools are simply hidden) instead of producing undefined behaviour.
powermemory_ready = False

if app_config.agent_powermem_config is not None:
    # for group memory, the key is f"group_{chat_id}"
    powermemory = AsyncMemory(app_config.agent_powermem_config)

    async def _init_powermem():
        global powermemory_ready
        assert powermemory is not None
        try:
            await powermemory.initialize()
            powermemory_ready = True
            logger.info("powermem initialized successfully")
        except Exception as e:
            logger.exception(
                f"Failed to initialize powermem, group memory tools will be "
                f"disabled: {e.__class__.__name__} - {e}"
            )

    common.spawn(_init_powermem(), name="powermem-init")


_bot_user_wake_locks: dict[int, asyncio.Lock] = {}

_BOT_WAKE_DELAY_MIN_SECONDS = 0.721
_BOT_WAKE_DELAY_MAX_SECONDS = 12.7


def _get_bot_user_wake_lock(user_id: int) -> asyncio.Lock:
    lock = _bot_user_wake_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _bot_user_wake_locks[user_id] = lock
    return lock


async def history_processor(
    ctx: RunContext[datatype.ContextDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    # Compaction (history.compact_history): runs on the current run's model
    # with the same system prompt as the conversation, so the provider prompt
    # cache is reused. Preserves deferred tool calls and trims multimodal
    # content; skipped entirely when disabled in config. Compaction is pure
    # history rewriting; user-memory extraction is a separate mechanism.
    compressed = await compact_history(messages, ctx.model, deps=ctx.deps, agent=agent)

    # Cache the compressed history
    await common.memttlcache.set(
        state.history_key(ctx.deps.chat_id, ctx.deps.user_id),
        compressed,
        ttl=app_config.cachettl_agent_history,
    )

    return compressed


if app_config.agent and app_config.agent_model:
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
    struct_model = (
        model
        if not app_config.agent_struct_model
        else provider.make_chat_model(app_config.agent_struct_model)
    )
    agent = Agent(
        model=model,
        model_settings=provider.make_model_settings(app_config.agent_model_options),
        # instructions=app_config.agent_prompt,
        output_type=[str, datatype.EndTurn, tools.ask_user],
        tools=[
            Tool(
                tools.image_ops,
                prepare=tools.compose_prepare(
                    tools.prepare_not_guest_mode, tools.prepare_image_tools
                ),
            ),
            Tool(
                tools.tg,
                prepare=tools.prepare_not_guest_mode,
                sequential=True,
            ),
            Tool(
                tools.send_anime_photo,
                prepare=tools.compose_prepare(
                    tools.prepare_not_guest_mode, tools.prepare_manyacg_tools
                ),
                sequential=True,
            ),
            Tool(
                tools.send_sticker,
                prepare=tools.compose_prepare(
                    tools.prepare_not_guest_mode, tools.prepare_sticker_tools
                ),
                sequential=True,
            ),
            # Time tools
            Tool(
                tools.time_info
            ),  # Unified IO tools (protocol prefixes: kmua://, work://, telegram://, http(s)://)
            Tool(
                tools.read,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.write,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.edit,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.list,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.search,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.delete,
                prepare=tools.compose_prepare(
                    tools.prepare_io_tools, tools.prepare_not_guest_mode
                ),
            ),
            Tool(
                tools.shell,
                prepare=tools.compose_prepare(
                    tools.prepare_shell_tools, tools.prepare_not_guest_mode
                ),
                sequential=True,
            ),
        ],
        deps_type=datatype.ContextDeps,
        capabilities=safety.build_agent_capabilities(history_processor),
        retries=5,
    )

    @agent.instructions
    async def _dynamic_instructions(ctx: RunContext[datatype.ContextDeps]) -> str:
        return ctx.deps.instructions

    memory_agent = Agent(
        model=struct_model,
        model_settings=provider.make_model_settings(
            app_config.agent_struct_model_options
        ),
        output_type=datatype.UserMemoryResult,
        instructions=app_config.agent_memory_prompt,
        retries=5,
    )

    async def _run_agent_for_ask(
        client: PyrogramClient,
        message: pyrogram.types.Message,
        user_id: int,
        chat_id: int,
        user_prompt: str,
    ) -> None:
        """Start a new agent run to handle an ask_user answer (button click)."""
        if not app_config.agent or agent is None or not is_chat_allowed(chat_id):
            return
        if await tools.is_user_blocked(user_id):
            return
        user_config = await database.get_user_config(user_id)
        lang = user_config.lang
        history: list[ModelMessage] = await common.memttlcache.get(
            state.history_key(chat_id, user_id), []
        )
        is_group_chat = message.chat and message.chat.type in (
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
        prompt_override = await runner.get_chat_prompt_override(chat_id)
        if prompt_override:
            instructions = prompt_override

        await common.memstore.set(state.waiting_key(user_id), True)
        try:
            await runner.run_agent(
                agi=agent,  # type: ignore
                client=client,
                message=message,
                user_id=user_id,
                chat_id=chat_id,
                user_prompt=[user_prompt],
                history=history,
                deps=datatype.ContextDeps(
                    user_id=user_id,
                    chat_id=chat_id,
                    message=message,
                    client=client,
                    instructions=instructions,
                    powermemory=powermemory,
                    history=history,
                ),
                multimodal_model=multimodal_model,
                model=model,
                lang=lang,
            )
        finally:
            await common.memstore.delete(state.waiting_key(user_id))

    tools.set_run_callback(_run_agent_for_ask)

    @PyrogramClient.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: PyrogramClient, message: pyrogram.types.Message):
        if not app_config.agent:
            return
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
        if not is_chat_allowed(chat_id):
            return
        await common.memttlcache.delete(state.history_key(chat_id, user.id))
        await tools.clear_ask_state(chat_id, user.id)
        safety.delete_spill_session(f"{chat_id}_{user.id}")
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )

    @PyrogramClient.on_callback_query(
        pyrogram.filters.regex(r"^agent_clear_history:(-?\d+):(\d+)$"), group=0
    )
    async def on_clear_history_callback(
        client: PyrogramClient, callback_query: pyrogram.types.CallbackQuery
    ):
        if not app_config.agent:
            return
        data = str(callback_query.data)
        parts = data.split(":")
        target_chat_id = int(parts[1])
        target_user_id = int(parts[2])
        if not is_chat_allowed(target_chat_id):
            return

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
        safety.delete_spill_session(f"{target_chat_id}_{target_user_id}")

        await callback_query.answer(
            i18n.t("bot.msg.agent.forgot", locale=lang), show_alert=False
        )
        if callback_query.message:
            await callback_query.message.edit_reply_markup(reply_markup=None)  # type: ignore

    @PyrogramClient.on_message(pyrogram.filters.command("model"), group=0)
    async def set_model_command(
        client: PyrogramClient, message: pyrogram.types.Message
    ):
        if not app_config.agent:
            return
        assert app_config.agent_model is not None, (
            "Unexcepted None value for agent_model"
        )
        user = message.from_user
        if not user or not user.id:
            return
        db_user = await database.get_user_by_id(user.id)
        if not db_user:
            return
        if not db_user.is_bot_global_admin and user.id not in app_config.owners:
            return
        current_chat_id = message.chat.id if message.chat else None
        if not current_chat_id:
            return
        if not is_chat_allowed(current_chat_id):
            return
        raw_args = message.text.split() if message.text else []
        # Remove the command itself ("/model")
        raw_args = raw_args[1:]

        # --- Parse optional @<chat_id> target prefix ---
        # If the first argument starts with '@' followed by digits (possibly negative),
        # it specifies the target chat. Otherwise, the current chat is used.
        target_chat_id = current_chat_id
        target_chat_label: str | None = None  # Human-readable label for the target chat
        if raw_args and raw_args[0].startswith("@"):
            maybe_id = raw_args[0][1:]  # strip the '@'
            # Allow negative IDs (group/supergroup chats start with '-')
            if maybe_id.lstrip("-").isdigit() and maybe_id not in ("", "-"):
                target_chat_id = int(maybe_id)
                raw_args = raw_args[1:]
                # Try to resolve a human-readable title for the target chat
                try:
                    tg_chat = await client.get_chat(target_chat_id)
                    if hasattr(tg_chat, "title") and tg_chat.title:
                        target_chat_label = f"{tg_chat.title} ({target_chat_id})"
                    elif hasattr(tg_chat, "first_name") and tg_chat.first_name:
                        target_chat_label = f"{tg_chat.first_name} ({target_chat_id})"
                except Exception:
                    pass
                if not target_chat_label:
                    target_chat_label = str(target_chat_id)

        if not is_chat_allowed(target_chat_id):
            return

        is_remote = target_chat_id != current_chat_id
        chat_display = target_chat_label or str(target_chat_id)
        chat_desc = f"chat <code>{chat_display}</code>" if is_remote else "this chat"

        # Subcommand dispatch: /model [@chat_id] [main|multimodal|small] [model_spec]
        # /model [@chat_id]                  → show current overrides
        # /model [@chat_id] <spec>           → set both main and multimodal to spec
        # /model [@chat_id] main [spec]      → set/reset main model only
        # /model [@chat_id] multimodal [spec]→ set/reset multimodal model only
        # /model [@chat_id] small [spec]     → set/reset small model only

        SUBCOMMANDS = {"main", "multimodal", "small"}

        subcommand: str | None = None
        model_name: str | None = None

        if len(raw_args) == 0:
            # /model  or  /model @chat_id  → show current overrides
            subcommand = None
            model_name = None
        elif len(raw_args) == 1:
            arg1 = raw_args[0].strip()
            if arg1 in SUBCOMMANDS:
                # /model [main|multimodal|small]  → reset that model
                subcommand = arg1
                model_name = None
            else:
                # /model <spec>  → set both main and multimodal
                subcommand = "both"
                model_name = arg1
        else:
            # len >= 2
            arg1 = raw_args[0].strip()
            if arg1 in SUBCOMMANDS:
                subcommand = arg1
                model_name = " ".join(raw_args[1:]).strip()
            else:
                # Unrecognised, treat whole remainder as both main+multimodal spec
                subcommand = "both"
                model_name = " ".join(raw_args).strip()

        # --- No subcommand: show current state ---
        if subcommand is None:
            cur_main = await get_chat_model_override(target_chat_id, "main")
            cur_mm = await get_chat_model_override(target_chat_id, "multimodal")
            cur_small = await get_chat_model_override(target_chat_id, "small")
            lines = [
                f"<b>Current model overrides for {chat_desc}:</b>",
                f"  main:       <code>{cur_main or '(global default: ' + app_config.agent_model + ')'}</code>",
                f"  multimodal: <code>{cur_mm or '(global default: ' + (app_config.agent_model_multimodal or app_config.agent_model) + ')'}</code>",
                f"  small:      <code>{cur_small or '(global default: ' + (app_config.agent_model_small or app_config.agent_model) + ')'}</code>",
                "",
                "Usage: <code>/model [@chat_id] [main|multimodal|small] [model_spec]</code>",
                "Omit model_spec to reset to global default.",
                "Omit @chat_id to target the current chat.",
            ]
            await message.reply_text(
                "\n".join(lines),
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            return

        # --- Handle both main+multimodal (no subcommand given) ---
        if subcommand == "both":
            prev_main = (
                await get_chat_model_override(target_chat_id, "main")
                or app_config.agent_model
            )
            prev_mm = await get_chat_model_override(target_chat_id, "multimodal") or (
                app_config.agent_model_multimodal or app_config.agent_model
            )
            await set_chat_model_override(target_chat_id, model_name, "main")
            await set_chat_model_override(target_chat_id, model_name, "multimodal")
            await message.reply_text(
                f"Main and multimodal model for {chat_desc} set to <code>{model_name}</code> "
                f"(was: main=<code>{prev_main}</code>, multimodal=<code>{prev_mm}</code>).",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            logger.info(
                f"Admin {user.id} set main+multimodal model override for chat {target_chat_id}: "
                f"main {prev_main!r} → {model_name!r}, multimodal {prev_mm!r} → {model_name!r}"
            )

        # --- Handle main model only ---
        elif subcommand == "main":
            current = await get_chat_model_override(target_chat_id, "main")
            if model_name:
                await set_chat_model_override(target_chat_id, model_name, "main")
                prev = current or app_config.agent_model
                await message.reply_text(
                    f"Main model for {chat_desc} set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set main model override for chat {target_chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(target_chat_id, None, "main")
                prev = current or app_config.agent_model
                await message.reply_text(
                    f"Main model for {chat_desc} reset to global default "
                    f"<code>{app_config.agent_model}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset main model override for chat {target_chat_id} "
                    f"(was: {current!r})"
                )

        # --- Handle multimodal model only ---
        elif subcommand == "multimodal":
            current = await get_chat_model_override(target_chat_id, "multimodal")
            global_default = app_config.agent_model_multimodal or app_config.agent_model
            if model_name:
                await set_chat_model_override(target_chat_id, model_name, "multimodal")
                prev = current or global_default
                await message.reply_text(
                    f"Multimodal model for {chat_desc} set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set multimodal model override for chat {target_chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(target_chat_id, None, "multimodal")
                prev = current or global_default
                await message.reply_text(
                    f"Multimodal model for {chat_desc} reset to global default "
                    f"<code>{global_default}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset multimodal model override for chat {target_chat_id} "
                    f"(was: {current!r})"
                )

        # --- Handle small model only ---
        elif subcommand == "small":
            current = await get_chat_model_override(target_chat_id, "small")
            global_default = app_config.agent_model_small or app_config.agent_model
            if model_name:
                await set_chat_model_override(target_chat_id, model_name, "small")
                prev = current or global_default
                await message.reply_text(
                    f"Small model for {chat_desc} set to <code>{model_name}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} set small model override for chat {target_chat_id}: "
                    f"{prev!r} → {model_name!r}"
                )
            else:
                await set_chat_model_override(target_chat_id, None, "small")
                prev = current or global_default
                await message.reply_text(
                    f"Small model for {chat_desc} reset to global default "
                    f"<code>{global_default}</code> "
                    f"(was: <code>{prev}</code>).",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
                )
                logger.info(
                    f"Admin {user.id} reset small model override for chat {target_chat_id} "
                    f"(was: {current!r})"
                )

    @PyrogramClient.on_message(pyrogram.filters.command("prompt"), group=0)
    async def set_prompt_command(
        client: PyrogramClient, message: pyrogram.types.Message
    ):
        if not app_config.agent:
            return
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
        if not is_chat_allowed(chat_id):
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
    # WeChat article links are handled by the link parser (group -1).
    & ~pyrogram.filters.regex(r"https?://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+")
    # Twitter/X links are handled by the native tweet parser (group -1).
    & ~pyrogram.filters.regex(r"(?:twitter|x)\.com/[^/]+/status/\d+")
    # Coolapk/Tieba links are handled by the link parser (group -1).
    & ~pyrogram.filters.regex(link_parse.SOCIAL_URL_RE.pattern)
)

_chat_command_filter = (
    pyrogram.filters.command("chat") & myfilter.not_bottle_reply_filter
)


@PyrogramClient.on_message(_filter | _chat_command_filter, group=0)
async def wake_agent(client: PyrogramClient, message: pyrogram.types.Message):
    # some check
    if not app_config.agent or not agent:
        return await word_reply(client, message)
    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return await word_reply(client, message)
    chat = message.chat
    if not chat or not chat.id:
        return await word_reply(client, message)
    chat_config = None
    if not is_chat_allowed(chat.id):
        return await word_reply(client, message)
    if chat.type == pyrogram.enums.ChatType.SUPERGROUP:
        chat_config = await database.get_chat_config(chat)
        if not chat_config.ai_reply:
            return await word_reply(client, message)
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    is_bot_user = bool(user_data.is_bot)
    if await tools.is_user_blocked(user.id):
        return
    if (
        is_bot_user
        and chat.type == pyrogram.enums.ChatType.SUPERGROUP
        and chat_config is not None
        and not chat_config.ai_reply_other_bots_enabled
    ):
        return

    bot_user_wake_lock: asyncio.Lock | None = None
    bot_user_wake_lock_acquired = False
    if is_bot_user:
        bot_user_wake_lock = _get_bot_user_wake_lock(user.id)
        if bot_user_wake_lock.locked():
            return
        await bot_user_wake_lock.acquire()
        bot_user_wake_lock_acquired = True

    waiting_marked = False
    try:
        if await common.memstore.get(state.waiting_key(user.id)):
            if is_bot_user:
                return
            return await message.reply_text("Thinking...")

        # Check if there's a pending ask — clear it and let the normal flow handle
        # the new message (the ask context is already in history).
        ask_state = await tools.get_ask_state(chat.id, user.id)
        if ask_state is not None:
            await tools.clear_ask_state(chat.id, user.id)
            logger.info(
                f"Cleared pending ask for user {user.id}, proceeding with normal agent run"
            )

        await common.memstore.set(state.waiting_key(user.id), True)
        waiting_marked = True
        # set language
        if chat.type == pyrogram.enums.ChatType.PRIVATE:
            lang = (await database.get_user_config(user.id)).lang
        else:
            lang = (await database.get_chat_config(chat.id)).lang

        # agent run
        if is_bot_user:
            await asyncio.sleep(
                random.uniform(
                    _BOT_WAKE_DELAY_MIN_SECONDS,
                    _BOT_WAKE_DELAY_MAX_SECONDS,
                )
            )
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
        if waiting_marked:
            await common.memstore.delete(state.waiting_key(user.id))
        if bot_user_wake_lock_acquired and bot_user_wake_lock is not None:
            bot_user_wake_lock.release()


@PyrogramClient.on_guest_message(group=0)
async def on_guest_chat_query(
    client: PyrogramClient,
    message: pyrogram.types.Message,
):
    """Handle guest bot messages (Layer 225)."""
    if not app_config.agent or not agent:
        return

    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return

    chat = message.chat
    if not chat or not chat.id:
        return
    if not is_chat_allowed(chat.id):
        return

    if await common.memstore.get(state.waiting_key(user.id)):
        return

    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    if await tools.is_user_blocked(user.id):
        return

    await common.memstore.set(state.waiting_key(user.id), True)
    try:
        user_message_text = message.text or message.caption or ""
        if user_message_text:
            logger.debug(
                f"User {user.id} wake agent [guest] in Chat {chat.id}: {user_message_text}"
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
        prompt_override = await get_chat_prompt_override(chat.id)
        if prompt_override:
            instructions = prompt_override

        history: list[ModelMessage] = await common.memttlcache.get(
            state.history_key(chat.id, user.id), []
        )

        ctx_info = await build_ctx_info(
            message=message,
            user=user,
            user_data=user_data,
            history=history,
            is_group_chat=is_group_chat,
        )

        user_prompt, _ = await get_input_prompt(
            client, message, include_nearby=0, ctx=None
        )

        await run_agent(
            agi=agent,  # type: ignore[arg-type]
            additional_instructions=ctx_info.to_text() if ctx_info else None,
            client=client,
            message=message,
            user_id=user.id,
            chat_id=chat.id,
            user_prompt=user_prompt,
            history=history,
            deps=datatype.ContextDeps(
                user_id=user.id,
                chat_id=chat.id,
                message=message,
                client=client,
                instructions=instructions,
                powermemory=powermemory,
                history=history,
            ),
            multimodal_model=multimodal_model,
            model=model,
            lang=user_data.user_config.lang
            if user_data.user_config
            else app_config.lang,
        )
    finally:
        await common.memstore.delete(state.waiting_key(user.id))
