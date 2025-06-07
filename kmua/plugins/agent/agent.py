from io import BytesIO
from typing import Callable

import pydantic_ai
import pyrogram
import pyrogram.errors
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import UserContent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.manyacg import manyacg

from . import datatype, myfilter, tools, utils
from .simple_reply import word_reply

agent = None
if app_config.agent:
    model = OpenAIModel(
        model_name=app_config.agent_model,
        provider=OpenAIProvider(
            base_url=app_config.agent_provider_url,
            api_key=app_config.agent_api_key,
        ),
    )
    agent = Agent(
        model=model,
        system_prompt=app_config.agent_prompt,
        tools=[
            tools.get_history_messages,
            tools.get_current_time,
            tools.get_user_info,
            tools.get_chat_info,
            tools.send_anime_photo,
            tools.schedule_message,
            duckduckgo_search_tool(),
        ],
        deps_type=datatype.ContextDeps,  # type: ignore
        retries=3,
    )  # type: ignore
    summary_agent = Agent(model=model, system_prompt=app_config.agent_summary_prompt)

    @pyrogram.Client.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: pyrogram.Client, message: pyrogram.types.Message):
        user = message.sender_chat or message.from_user
        if not user or user.id is None:
            return
        user_config = await database.get_user_config(user.id)
        if await common.memstore.get(_waiting_key(user.id)):
            await message.reply_text(
                i18n.t("bot.msg.agent.waiting", locale=user_config.lang)
            )
            return
        chat_id = message.chat.id if message.chat else user.id
        if not chat_id:
            return
        await common.memttlcache.delete(_history_key(chat_id, user.id))
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )


def _history_key(chat_id: int, user_id: int) -> str:
    return f"message_history_with_agent:{chat_id}:{user_id}"


def _waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


_filter = (
    myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter)
    & ~pyrogram.filters.regex("|".join([r.pattern for r in manyacg.ARTWORK_ALL_REGEX]))
)


@pyrogram.Client.on_message(_filter, group=0)
async def wake_agent(client: pyrogram.Client, message: pyrogram.types.Message):
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
    if await common.memstore.get(_waiting_key(user.id)):
        return await word_reply(client, message)

    # set language
    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user.id)).lang
    else:
        lang = (await database.get_chat_config(chat.id)).lang

    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    await common.memstore.set(_waiting_key(user.id), True)
    # agent run
    try:
        chat_id = chat.id
        history = await common.memttlcache.get(_history_key(chat_id, user.id), [])
        user_prompt_text = message.text or message.caption or ""
        if reply_to := message.reply_to_message:
            user_prompt_text += (
                f"""
[REPLY TO MESSAGE](MessageID: {reply_to.id}):
{reply_to.text or reply_to.caption or "[NO TEXT]"}
"""
                if chat.type != pyrogram.enums.ChatType.PRIVATE
                else f"""
[REPLY TO MESSAGE]:
{reply_to.text or reply_to.caption or "[NO TEXT]"}
"""
            )
        context_info = (
            f"""
[CONTEXT INFO]:
MessageID: {message.id}
[USER MESSAGE]:
"""
            if chat.type != pyrogram.enums.ChatType.PRIVATE
            else f"""
[CONTEXT INFO]:
In Private Chat
[USER MESSAGE]:
"""
        )
        user_prompt: list[UserContent] = [
            f"{context_info}{user_prompt_text}",
        ]
        get_media_and_message: Callable[
            [pyrogram.types.Message],
            tuple[
                pyrogram.enums.MessageMediaType | None, pyrogram.types.Message | None
            ],
        ] = lambda m: (
            (m.media, m)
            if m.media
            else (m.reply_to_message.media, m.reply_to_message)
            if m.reply_to_message and m.reply_to_message.media
            else (None, None)
        )
        media, media_message = get_media_and_message(message)
        if media and media_message and app_config.agent_multimodal:
            match media:
                case pyrogram.enums.MessageMediaType.PHOTO:
                    if media_message.photo and media_message.photo.file_id:
                        photo_file = await client.download_media(
                            media_message.photo.file_id, in_memory=True
                        )
                        if isinstance(photo_file, BytesIO):
                            photo_bytes = photo_file.getvalue()
                            user_prompt.append(
                                BinaryContent(data=photo_bytes, media_type="image/jpeg")
                            )

        logger.debug(f"User {user.id} prompt: {user_prompt_text}")
        repiled: pyrogram.types.Message | None = None

        async def _reply_or_edit(text: str, final: bool = False):
            nonlocal repiled
            try:
                if repiled:
                    if final:
                        await repiled.edit_text(text)
                        return
                    if repiled.text and text.startswith(repiled.text):
                        await repiled.edit_text(text)
                    elif repiled.text and (len(repiled.text) + len(text)) < 1000:
                        await repiled.edit_text(repiled.text + "\n" + text)
                    else:
                        repiled = await repiled.edit_text(text)
                else:
                    repiled = await message.reply_text(text)
            except pyrogram.errors.MessageNotModified:
                pass
            except Exception as e:
                logger.error(
                    f"Error replying or editing message: {e.__class__.__name__} - {e}"
                )

        try:
            async with agent.iter(
                user_prompt,
                message_history=history,
                deps=datatype.ContextDeps(
                    user_id=user.id,
                    chat_id=chat_id,
                    message=message,
                    client=client,
                ),  # type: ignore
            ) as agent_run:
                async for node in agent_run:
                    if Agent.is_call_tools_node(node):
                        for part in node.model_response.parts:
                            if part.part_kind == "text" and part.content:
                                await _reply_or_edit(part.content)
                    elif Agent.is_end_node(node):
                        if agent_run.result:
                            logger.debug(
                                f"Agent run end with result: {agent_run.result.output}"
                            )
                            await _reply_or_edit(agent_run.result.output, final=True)
                            summary = await utils.summarize_history(
                                summary_agent, agent_run.result.all_messages()
                            )
                            await common.memttlcache.set(
                                _history_key(chat_id, user.id),
                                summary,
                                ttl=app_config.cachettl_agent_history,
                            )
                        else:
                            logger.error(
                                f"Agent run ended with no result for user {user.id} in chat {chat_id}"
                            )
        except TypeError as e:
            # https://github.com/pydantic/pydantic-ai/issues/527
            # https://github.com/pydantic/pydantic-ai/issues/1813
            logger.exception(f"Agent run error: {e}")
            await message.reply_text(
                f"{i18n.t('bot.msg.agent.errors.too_fast', locale=lang)}\n<code>{e}</code>",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            raise e
        except pydantic_ai.exceptions.ModelHTTPError as e:
            logger.exception(f"Agent HTTP error: {e}")
            if e.status_code == 400:
                await message.reply_text(
                    i18n.t("bot.msg.agent.errors.model_http_400", locale=lang)
                )
                return
            else:
                await message.reply_text(
                    i18n.t("bot.msg.agent.errors.model_http", locale=lang).format(
                        code=e.status_code
                    )
                )
            return

    finally:
        await common.memstore.delete(_waiting_key(user.id))
