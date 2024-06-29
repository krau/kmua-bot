import pickle
import random

import vertexai
import zhconv
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

from kmua import common
from kmua.config import settings
from kmua.logger import logger

from .friendship import ohayo, oyasumi

_SYSTEM_INSTRUCTION = settings.get("vertex_system")
_PROJECT_ID = settings.get("vertex_project_id")
_LOCATION = settings.get("vertex_location")
_enable_vertex = (
    all((_SYSTEM_INSTRUCTION, _PROJECT_ID, _LOCATION)) and common.redis_client
)
_model = None
_preset_contents: list[Content] = []

if _enable_vertex:
    logger.debug("Initializing Vertex AI")
    try:
        vertexai.init(project=_PROJECT_ID, location=_LOCATION)
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
        for i, content in enumerate(settings.get("vertex_preset", [])):
            if i % 2 == 0:
                _preset_contents.append(
                    Content(
                        role="user",
                        parts=[Part.from_text(content)],
                    )
                )
            else:
                _preset_contents.append(
                    Content(
                        role="model",
                        parts=[Part.from_text(content)],
                    )
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
    message_text = zhconv.convert(message_text, "zh-cn")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    if not (_enable_vertex and not_aonymous):
        await _keyword_reply_without_save(update, context, message_text)
        return

    contents: bytes = common.redis_client.get(
        f"kmua_contents_{update.effective_user.id}"
    )
    if not contents:
        contents = pickle.dumps(_preset_contents)
        common.redis_client.set(
            f"kmua_contents_{update.effective_user.id}", contents, ex=2 * 24 * 60 * 60
        )
    contents: list[Content] = pickle.loads(contents)
    if len(contents) <= 2:
        await _keyword_reply(update, context, message_text)
        return
    try:
        if context.bot_data.get("vertex_block", False):
            await _keyword_reply_without_save(update, context, message_text)
            return
        context.bot_data["vertex_block"] = True
        contents.append(
            Content(
                role="user",
                parts=[Part.from_text(message_text)],
            )
        )
        resp = await _model.generate_content_async(contents)
        if resp.candidates[0].finish_reason not in (
            FinishReason.STOP,
            FinishReason.MAX_TOKENS,
        ):
            logger.warning(f"Vertex AI finished unexpectedly: {resp}")
            contents.pop()
            await _keyword_reply(update, context, message_text)
            return
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
        common.redis_client.set(
            f"kmua_contents_{update.effective_user.id}",
            pickle.dumps(contents),
            ex=2 * 24 * 60 * 60,
        )
    except Exception as e:
        logger.error(f"Failed to generate content: {e}")
        if (
            "Please ensure that multiturn requests alternate between user and model"
            in e
        ):
            contents.pop()
            common.redis_client.set(
                f"kmua_contents_{update.effective_user.id}",
                pickle.dumps(contents),
                ex=2 * 24 * 60 * 60,
            )
        await _keyword_reply_without_save(update, context, message_text)
    finally:
        if len(contents) > 16:
            contents = contents[-16:]
            common.redis_client.set(
                f"kmua_contents_{update.effective_user.id}",
                pickle.dumps(contents),
                ex=2 * 24 * 60 * 60,
            )
        context.bot_data["vertex_block"] = False


async def _keyword_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str
):
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
        if not_aonymous and _enable_vertex:
            contents: bytes = common.redis_client.get(
                f"kmua_contents_{update.effective_user.id}"
            )
            if not contents:
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
                common.redis_client.set(
                    f"kmua_contents_{update.effective_user.id}",
                    pickle.dumps(contents),
                    ex=2 * 24 * 60 * 60,
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
                if len(contents) > 16:
                    contents = contents[-16:]
                common.redis_client.set(
                    f"kmua_contents_{update.effective_user.id}",
                    pickle.dumps(contents),
                    ex=2 * 24 * 60 * 60,
                )
    return


async def _keyword_reply_without_save(
    update: Update, _: ContextTypes.DEFAULT_TYPE, message_text: str
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
    if not _enable_vertex:
        return
    common.redis_client.delete(f"kmua_contents_{update.effective_user.id}")
    await update.effective_message.reply_text("刚刚发生了什么...好像忘记了呢")


async def clear_all_contents(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_vertex:
        return
    if not common.verify_user_can_manage_bot(update.effective_user):
        return
    try:
        keys = common.redis_client.keys("kmua_contents_*")
        for key in keys:
            common.redis_client.delete(key)
        await update.effective_message.reply_text("已清除所有用户的对话记录")
    except Exception as e:
        logger.error(f"Failed to clear all contents: {e}")
        await update.effective_message.reply_text("清除失败")
