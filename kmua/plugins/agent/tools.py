import random

import pyrogram
from pydantic import BaseModel
from pydantic_ai import RunContext

import kmua.plugins
import kmua.plugins.manyacg
import kmua.plugins.manyacg.manyacg
from kmua import database, i18n
from kmua.config import app_config
from kmua.logger import logger

from . import types


class UserInfo(BaseModel):
    user_id: int
    full_name: str
    username: str | None = None


async def get_user_info(ctx: RunContext[types.ContextDeps]) -> UserInfo:
    user_db = await database.get_user_by_id(ctx.deps.user_id)
    return UserInfo(
        user_id=user_db.id,
        full_name=user_db.full_name,
        username=user_db.username,
    )


class ChatInfo(BaseModel):
    chat_id: int
    title: str
    username: str | None = None
    config: dict


async def get_chat_info(ctx: RunContext[types.ContextDeps]) -> ChatInfo | None:
    if ctx.deps.chat_id is None:
        user_db = await database.get_user_by_id(ctx.deps.user_id)
        return ChatInfo(
            chat_id=user_db.id,
            title=user_db.full_name,
            username=user_db.username,
            config=user_db.config,
        )
    chat_db = await database.get_chat_by_id(ctx.deps.chat_id)
    if chat_db is None:
        return None
    return ChatInfo(
        chat_id=chat_db.id,
        title=chat_db.title,
        username=chat_db.username,
        config=chat_db.config,
    )


async def get_and_send_a_anime_photo(ctx: RunContext[types.ContextDeps]) -> bool:
    """Get and send a random anime photo (some users call it setu/涩图).

    Returns:
        bool: True if the photo was sent successfully, False otherwise.
    """
    if ctx.deps.message_id is None:
        return False
    try:
        user_config = await database.get_user_config(ctx.deps.user_id)
        lang = user_config.lang
        resp = await kmua.plugins.manyacg.manyacg.httpx_client.get(
            url="/artwork/random", params={"r18": 2}
        )
        if resp.status_code != 200:
            return False
        artwork: dict = resp.json()["data"][0]
        picture: dict = artwork["pictures"][
            random.randint(0, len(artwork["pictures"]) - 1)
        ]
        detail_link = (
            f"https://t.me/{app_config.manyacg_channel}/{picture['message_id']}"
            if picture.get("message_id")
            else artwork["source_url"]
        )
        await ctx.deps.client.send_photo(
            chat_id=ctx.deps.chat_id,
            photo=picture["regular"],
            caption=f"<a href='{artwork['source_url']}'>{artwork['title']}</a>",
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.detail", locale=lang),
                            url=detail_link,
                        ),
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.original", locale=lang),
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture['id']}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork["r18"],
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message_id,
            ),
        )
        return True
    except Exception as e:
        logger.error(f"get_and_send_a_anime_photo error: {e.__class__.__name__}:{e}")
        return False
