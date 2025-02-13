import re

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from kmua import dao
from kmua.logger import logger


async def bililink_convert(update: Update, context: ContextTypes):
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({update.effective_user.name})" + f" {message.text}")
    text = message.text
    is_group = chat.type in (chat.GROUP, chat.SUPERGROUP)
    if is_group and not dao.get_chat_config(chat).convert_b23_enabled:
        return
    # 匹配 b23.tv 或 bili2233.cn 后面的字符
    b23code = re.search(r"(?:b23\.tv|bili2233\.cn)/([a-zA-Z0-9]+)", text)
    if b23code:
        await _b23_convert(update, context, b23code.group().split("/")[-1], is_group)
        if is_group:
            try:
                await message.delete()
            except Exception:
                pass
        return


async def _b23_convert(update: Update, _: ContextTypes, b23code: str, is_group: bool):
    logger.debug(f"b23code: {b23code}")
    message = update.effective_message
    request_url = f"https://b23.tv/{b23code}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url=request_url,
        )
        real_url: str = resp.headers.get("Location")
    if real_url:
        real_url = real_url.split("?")[0]
        text = real_url
        if is_group:
            text += f"\n来自 {update.effective_user.name} 发送的 b23 短链接, 已经帮你转换了哦"
        await message.reply_text(text, quote=True)
    else:
        logger.error(f"b23 convert error: {resp.status_code}")
