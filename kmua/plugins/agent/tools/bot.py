import random

import pyrogram
from pydantic_ai import RunContext

import kmua.plugins
import kmua.plugins.manyacg
import kmua.plugins.manyacg.manyacg
from kmua import database, i18n
from kmua.config import app_config
from kmua.logger import logger

from .. import datatype


async def get_and_send_a_anime_photo(
    ctx: RunContext[datatype.ContextDeps],
) -> tuple[bool, str | None]:
    """Get and send a random anime photo (some users call it setu/涩图).

    Returns:
        A tuple of (success: bool, error_message: str | None).
        If success is True, the photo is sent successfully.
        If success is False, error_message contains the error message.
    """
    if ctx.deps.message_id is None:
        return False, "Message ID is required to reply with the photo."
    if (
        ctx.deps.chat_id is not None
        and not (await database.get_chat_config(ctx.deps.chat_id)).setu_enabled
    ):
        return False, "feature is disabled by chat administrator."
    try:
        user_config = await database.get_user_config(ctx.deps.user_id)
        lang = user_config.lang
        resp = await kmua.plugins.manyacg.manyacg.httpx_client.get(
            url="/artwork/random", params={"r18": 2}
        )
        if resp.status_code != 200:
            return False, f"Api request failed with code: {resp.status_code}"
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
        return True, None
    except Exception as e:
        logger.error(f"get_and_send_a_anime_photo error: {e.__class__.__name__}:{e}")
        return False, e.__class__.__name__
