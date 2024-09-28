import pickle
import random
from typing import Iterable

import zhconv
from openai.types.chat import ChatCompletionMessageParam
from telegram import (
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.config import settings
from kmua.logger import logger

from .friendship import ohayo, oyasumi

_enable_openai = all((common.openai_client, common.redis_client))
_system_message = {"role": "system", "content": common.openai_system}
_preset_contents: Iterable[ChatCompletionMessageParam] = [_system_message]
for i, message in enumerate(settings.get("openai_preset", [])):
    _preset_contents.append(
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": message,
        }
    )


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
    if not (_enable_openai and not_aonymous):
        await _keyword_reply_without_save(update, context, message_text)
        return

    if update.effective_chat.type in (
        update.effective_chat.GROUP,
        update.effective_chat.SUPERGROUP,
    ):
        chat_config = dao.get_chat_config(update.effective_chat)
        if not chat_config.ai_reply:
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
    contents: list[ChatCompletionMessageParam] = pickle.loads(contents)
    if len(contents) <= 2:
        await _keyword_reply(update, context, message_text)
        return
    try:
        if context.bot_data.get("openai_answering", False):
            await _keyword_reply_without_save(update, context, message_text)
            return
        context.bot_data["openai_answering"] = True
        contents.append(
            {
                "role": "user",
                "content": message_text,
            }
        )
        resp = common.openai_client.chat.completions.create(
            model=common.openai_model,
            messages=contents,
        )
        if resp.choices[0].finish_reason not in ("stop", "length"):
            logger.warning(f"OpenAI finished unexpectedly: {resp}")
            contents.pop()
            await _keyword_reply(update, context, message_text)
            return
        await update.effective_message.reply_text(
            text=resp.choices[0].message.content,
            quote=True,
        )
        logger.info("Bot: " + resp.choices[0].message.content)
        contents.append(
            {
                "role": "assistant",
                "content": resp.choices[0].message.content,
            }
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
            in str(e)
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
        context.bot_data["openai_answering"] = False


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
    if not all_resplist:
        return
    sent_message = await update.effective_message.reply_text(
        text=random.choice(all_resplist),
        quote=True,
    )
    logger.info("Bot: " + sent_message.text)
    if not (_enable_openai and not_aonymous):
        return
    contents: bytes = common.redis_client.get(
        f"kmua_contents_{update.effective_user.id}"
    )
    if not contents:
        contents = [
            {
                "role": "user",
                "content": message_text,
            },
            {
                "role": "assistant",
                "content": sent_message.text,
            },
        ]
        common.redis_client.set(
            f"kmua_contents_{update.effective_user.id}",
            pickle.dumps(contents),
            ex=2 * 24 * 60 * 60,
        )
    else:
        contents: list[ChatCompletionMessageParam] = pickle.loads(contents)
        contents.append(
            {
                "role": "user",
                "content": message_text,
            }
        )
        contents.append(
            {
                "role": "assistant",
                "content": sent_message.text,
            }
        )
        if len(contents) > 16:
            contents = contents[-16:]
        common.redis_client.set(
            f"kmua_contents_{update.effective_user.id}",
            pickle.dumps(contents),
            ex=2 * 24 * 60 * 60,
        )


async def _keyword_reply_without_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str
):
    all_resplist = []
    for keyword, resplist in common.word_dict.items():
        if keyword in message_text:
            all_resplist.extend(resplist)
            if keyword == "早":
                await ohayo(update, context)
            if keyword == "晚安":
                await oyasumi(update, context)
    if all_resplist:
        await update.effective_message.reply_text(
            text=random.choice(all_resplist),
            quote=True,
        )


async def reset_contents(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_openai:
        return
    common.redis_client.delete(f"kmua_contents_{update.effective_user.id}")
    await update.effective_message.reply_text("刚刚发生了什么...好像忘记了呢")


async def clear_all_contents(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_openai:
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
        await update.effective_message.reply_text(f"清除失败: {e}")
