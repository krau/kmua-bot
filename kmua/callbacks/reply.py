import pickle
import random

import redis
import vertexai
from telegram import (
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from vertexai.generative_models import (
    Content,
    FinishReason,
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
    SafetySetting,
)
from zhconv import convert

from kmua import common
from kmua.config import settings
from kmua.logger import logger

from .friendship import ohayo, oyasumi

_SYSTEM_INSTRUCTION = settings.get("vertex_system")
_PROJECT_ID = settings.get("vertex_project_id")
_LOCATION = settings.get("vertex_location")
_REDIS_URL = settings.get("redis_url", "redis://localhost:6379/0")
_enable_vertex = all((_SYSTEM_INSTRUCTION, _PROJECT_ID, _LOCATION))
_redis_client = None
_model = None

if _enable_vertex:
    try:
        vertexai.init(project=_PROJECT_ID, location=_LOCATION)
        _redis_client = redis.from_url(_REDIS_URL)
        _model = GenerativeModel(
            model_name=settings.get("vertex_model", "gemini-1.5-flash"),
            system_instruction=_SYSTEM_INSTRUCTION,
            safety_settings=[
                SafetySetting(
                    category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=HarmBlockThreshold.BLOCK_NONE,
                )
            ],
            generation_config=GenerationConfig(
                max_output_tokens=1024,
            ),
        )
    except Exception as e:
        logger.error(f"Failed to initialize Vertex AI: {e}")
        _enable_vertex = False


async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    not_aonymous = update.effective_message.sender_chat is None
    message_text = update.effective_message.text.replace(
        context.bot.username, ""
    ).lower()
    message_text = convert(message_text, "zh-cn")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    if not (_enable_vertex and not_aonymous):
        await _keyword_reply(update, context, message_text)
        return

    if common.random_unit(0.2):
        await _keyword_reply_without_save(update, context, message_text)

    contents: bytes = _redis_client.get(f"kmua_contents_{update.effective_user.id}")
    if contents is None:
        contents = pickle.dumps([])
        _redis_client.set(f"kmua_contents_{update.effective_user.id}", contents)
        await _keyword_reply(update, context, message_text)
        return
    contents: list[Content] = pickle.loads(contents)
    if len(contents) <= 10:
        await _keyword_reply(update, context, message_text)
        return
    if context.user_data.get("vertex_block", False):
        await _keyword_reply_without_save(update, context, message_text)
        return
    try:
        context.user_data["vertex_block"] = True
        contents.append(
            Content(
                role="user",
                parts=[Part.from_text(message_text)],
            )
        )
        resp = await _model.generate_content_async(contents)
        if resp.candidates[0].finish_reason is not FinishReason.STOP:
            logger.warning(f"Vertex AI finished unexpectedly: {resp}")
            contents.pop()
            await _keyword_reply(update, context, message_text)
            return
        logger.debug(f"Vertex AI response: {resp}")
        await update.effective_message.reply_text(
            text=resp.text,
            quote=True,
        )
        logger.info("Bot: " + resp.text)
        contents.append(
            Content(
                role="model",
                parts=[Part.from_text(resp.text)],
            )
        )
        _redis_client.set(
            f"kmua_contents_{update.effective_user.id}", pickle.dumps(contents)
        )
    except Exception as e:
        logger.error(f"Failed to generate content: {e}")
        await _keyword_reply(update, context, message_text)
    finally:
        if len(contents) > 20:
            contents = contents[-20:]
            _redis_client.set(
                f"kmua_contents_{update.effective_user.id}", pickle.dumps(contents)
            )
        context.user_data["vertex_block"] = False


async def _keyword_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str
):
    if context.user_data.get("vertex_block", False):
        return
    context.user_data["vertex_block"] = True
    sent_message = None
    all_resplist = []
    not_aonymous = update.effective_message.sender_chat is None
    for keyword, resplist in common.word_dict.items():
        if keyword in message_text:
            all_resplist.extend(resplist)
            if keyword == "早":
                await ohayo(update, context)
            if keyword == "晚安":
                await oyasumi(update, context)
    if all_resplist:
        sent_message = await update.effective_message.reply_text(
            text=random.choice(all_resplist),
            quote=True,
        )
        logger.info("Bot: " + sent_message.text)
        if not_aonymous:
            contents: bytes = _redis_client.get(
                f"kmua_contents_{update.effective_user.id}"
            )
            if contents is None:
                contents = [
                    Content(
                        role="user",
                        parts=[Part.from_text(message_text)],
                    ),
                    Content(
                        role="model",
                        parts=[Part.from_text(sent_message.text)],
                    ),
                ]
                _redis_client.set(
                    f"kmua_contents_{update.effective_user.id}", pickle.dumps(contents)
                )
            else:
                contents: list[Content] = pickle.loads(contents)
                contents.append(
                    Content(
                        role="user",
                        parts=[Part.from_text(message_text)],
                    )
                )
                contents.append(
                    Content(
                        role="model",
                        parts=[Part.from_text(sent_message.text)],
                    )
                )
                if len(contents) > 20:
                    contents = contents[-20:]
                _redis_client.set(
                    f"kmua_contents_{update.effective_user.id}", pickle.dumps(contents)
                )
    common.message_recorder(update, context)
    context.user_data["vertex_block"] = False
    return


async def _keyword_reply_without_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str
):
    all_resplist = []
    for keyword, resplist in common.word_dict.items():
        if keyword in message_text:
            all_resplist.extend(resplist)
    if all_resplist:
        await update.effective_message.reply_text(
            text=random.choice(all_resplist),
            quote=True,
        )


async def reset_contents(update: Update, _: ContextTypes.DEFAULT_TYPE):
    _redis_client.delete(f"kmua_contents_{update.effective_user.id}")
    await update.effective_message.reply_text("刚刚发生了什么...好像忘记了呢")
