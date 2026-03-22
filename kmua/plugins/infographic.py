"""
Infographic API integration plugin
Renders infographic syntax to images via infographic-api
"""

from io import BytesIO

import httpx
from pyrogram import enums, filters
from pyrogram.client import Client
from pyrogram.types import Message

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger


@Client.on_message(filters.command("infographic"), group=0)
async def infographic_command(client: Client, message: Message):
    """
    Render infographic syntax to image
    Usage: /infographic <infographic syntax>
    Reply to a message with /infographic to render the text as infographic
    """
    if not app_config.infographic:
        return

    chat = message.chat
    user = message.from_user
    if not chat or not user:
        return

    if chat.type == enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user)).lang
    else:
        lang = (await database.get_chat_config(chat)).lang

    # Get the infographic syntax from command args or replied message
    infographic_text = ""
    if message.reply_to_message and message.reply_to_message.text:
        infographic_text = message.reply_to_message.text
    elif message.command and len(message.command) > 1 and message.text:
        infographic_text = message.text.split(maxsplit=1)[1]

    if not infographic_text:
        await message.reply_text(i18n.t("bot.msg.infographic.usage", locale=lang))
        return

    # Check cooldown
    cd_key = f"infographic_cd:{chat.id}"
    if await common.memstore.get(cd_key):
        await message.reply_text(i18n.t("bot.msg.infographic.cooldown", locale=lang))
        return

    await common.memstore.set(cd_key, value=True)
    try:
        await message.reply_chat_action(enums.ChatAction.UPLOAD_PHOTO)

        # Call infographic API
        async with httpx.AsyncClient(timeout=60.0) as http_client:
            headers = {"Content-Type": "application/json"}
            if app_config.infographic_api_key:
                headers["Authorization"] = f"Bearer {app_config.infographic_api_key}"

            payload = {
                "data": infographic_text,
                "width": 1200,
                "height": 800,
                "format": "png",
                "dpr": 2,
            }

            response = await http_client.post(
                f"{app_config.infographic_api_url}/render",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            image_bytes = BytesIO(response.content)
            render_time = response.headers.get("X-Render-Time", "unknown")

            await message.reply_photo(
                photo=image_bytes,
                caption=i18n.t("bot.msg.infographic.rendered", locale=lang).format(
                    time=render_time
                ),
            )

    except httpx.TimeoutException:
        logger.warning("Infographic API timeout")
        await message.reply_text(i18n.t("bot.msg.infographic.timeout", locale=lang))
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Infographic API error: {e.response.status_code} - {e.response.text}"
        )
        await message.reply_text(
            i18n.t("bot.msg.infographic.error", locale=lang).format(
                error=f"HTTP {e.response.status_code}"
            )
        )
    except Exception as e:
        logger.exception(f"Infographic rendering error: {e}")
        await message.reply_text(
            i18n.t("bot.msg.infographic.error", locale=lang).format(error=str(e))
        )
    finally:
        await common.memstore.delete(cd_key)
