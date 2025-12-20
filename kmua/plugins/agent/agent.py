from datetime import datetime
from io import BytesIO
from typing import Callable

import pydantic_ai
import pyrogram
import pyrogram.errors
from ddgs import DDGS
from pydantic_ai import Agent, BinaryContent, ImageMediaType, Tool, VideoUrl
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.messages import UserContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient
from pyrogram.enums.parse_mode import ParseMode

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import manyacg

from . import datatype, myfilter, tools, utils
from .simple_reply import word_reply

agent = None
if app_config.agent:
    model = OpenAIChatModel(
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
            tools.send_anime_photo,
            tools.schedule_message,
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
        ],
        deps_type=datatype.ContextDeps,
        retries=3,
    )  # type: ignore
    summary_agent = Agent(model=model, system_prompt=app_config.agent_summary_prompt)
    memory_agent = Agent(
        model=model,
        output_type=datatype.MemoryAboutUser,
        system_prompt=app_config.agent_memory_prompt,
    )

    @PyrogramClient.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: PyrogramClient, message: pyrogram.types.Message):
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
        ctx_info = datatype.ContextInfo(
            user_data=datatype.UserData(
                user_id=user.id,
                full_name=user_data.full_name,
                username=user_data.username,
                config=user_data.config,
            ),
            chat_type=chat.type.name if chat.type else None,
            msg_id=message.id,
            current_time=datetime.now().isoformat(),
        )
        if reply_to := message.reply_to_message:
            ctx_info.reply_to_msg_id = reply_to.id
            ctx_info.reply_to_msg_text = reply_to.text or reply_to.caption
        memory = await common.memttlcache.get(f"user_memory_{user.id}")
        if memory:
            ctx_info.memory_about_user = memory
        user_prompt_text = f"{ctx_info}\n{message.text or message.caption or ''}"
        user_prompt: list[UserContent] = [user_prompt_text]
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
                    photo = media_message.photo
                    if (
                        "photo" in app_config.agent_multimodal_inputs
                        and photo
                        and photo.file_id
                    ):
                        photo_file = await client.download_media(
                            photo.file_id, in_memory=True
                        )
                        if isinstance(photo_file, BytesIO):
                            photo_bytes = photo_file.getvalue()
                            user_prompt.append(
                                BinaryContent(data=photo_bytes, media_type="image/jpeg")
                            )
                case pyrogram.enums.MessageMediaType.VIDEO:
                    video = media_message.video
                    if (
                        video
                        and video.file_id
                        and video.mime_type
                        and video.file_size
                        and video.file_size <= 20 * 1024 * 1024
                    ):
                        if "video" in app_config.agent_multimodal_inputs:
                            video_file = await client.download_media(
                                video.file_id, in_memory=True
                            )
                            if isinstance(video_file, BytesIO):
                                video_bytes = video_file.getvalue()
                                user_prompt.append(
                                    BinaryContent(
                                        data=video_bytes, media_type=video.mime_type
                                    )
                                )
                case pyrogram.enums.MessageMediaType.DOCUMENT:
                    document = media_message.document
                    if (
                        document
                        and document.file_id
                        and document.mime_type
                        and document.file_size <= 10 * 1024 * 1024
                    ):
                        if document.mime_type in app_config.agent_multimodal_inputs:
                            doc_file = await client.download_media(
                                document.file_id, in_memory=True
                            )
                            if isinstance(doc_file, BytesIO):
                                doc_bytes = doc_file.getvalue()
                                user_prompt.append(
                                    BinaryContent(
                                        data=doc_bytes, media_type=document.mime_type
                                    )
                                )
                        elif (
                            document.mime_type.startswith("image/")
                            and "photo" in app_config.agent_multimodal_inputs
                        ):
                            doc_file = await client.download_media(
                                document.file_id, in_memory=True
                            )
                            if isinstance(doc_file, BytesIO):
                                doc_bytes = doc_file.getvalue()
                                user_prompt.append(
                                    BinaryContent(
                                        data=doc_bytes,
                                        media_type=document.mime_type,
                                    )
                                )

        logger.debug(f"User {user.id} prompt: {user_prompt_text}")
        repiled: pyrogram.types.Message | None = None

        async def _reply_or_edit(text: str, final: bool = False):
            nonlocal repiled
            try:
                if repiled:
                    if final:
                        await repiled.edit_text(text, parse_mode=ParseMode.DISABLED)
                        return
                    if repiled.text and text.startswith(repiled.text):
                        await repiled.edit_text(text, parse_mode=ParseMode.DISABLED)
                    elif repiled.text and (len(repiled.text) + len(text)) < 1000:
                        await repiled.edit_text(
                            repiled.text + "\n" + text, parse_mode=ParseMode.DISABLED
                        )
                    else:
                        repiled = await repiled.edit_text(
                            text, parse_mode=ParseMode.DISABLED
                        )
                else:
                    repiled = await message.reply_text(
                        text, parse_mode=ParseMode.DISABLED
                    )
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
                            if (
                                len(agent_run.result.all_messages())
                                >= app_config.agent_messages_threshold
                            ):
                                # update memory
                                try:
                                    history_text = utils.get_history_text(
                                        agent_run.result.all_messages()
                                    )
                                    await utils.update_memory(
                                        memory_agent, history_text, user.id
                                    )
                                except Exception as e:
                                    logger.exception(
                                        f"Error updating memory for user {user.id}: {e.__class__.__name__} - {e}"
                                    )
                        else:
                            logger.error(
                                f"Agent run ended with no result for user {user.id} in chat {chat_id}"
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
