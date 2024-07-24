import re

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from kmua import dao
from kmua.config import settings
from kmua.logger import logger

_api_url: str = settings.get("bililink_convert_api")
_api_url = _api_url.removesuffix("/") if _api_url else None


async def bililink_convert(update: Update, context: ContextTypes):
    if not _api_url:
        return
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({update.effective_user.name})" + f" {message.text}")
    text = message.text
    is_group = chat.type in (chat.GROUP, chat.SUPERGROUP)
    if is_group and not dao.get_chat_config(chat).convert_b23_enabled:
        return
    # 匹配 b23.tv/ 后面的字符
    b23code = re.search(r"(?<=b23\.tv\/)[a-zA-Z0-9]+", text)
    if b23code:
        await _b23_convert(update, context, b23code.group(), is_group)
        if is_group:
            try:
                await message.delete()
            except Exception:
                pass
        return
    if is_group:
        return
    # bilibili.com/video/ 后面的字符
    bvavcode = re.search(r"(?<=bilibili\.com\/video\/)[a-zA-Z0-9]+", text)
    if bvavcode:
        await _bvav_convert(update, context, bvavcode.group())
        return


async def _b23_convert(update: Update, _: ContextTypes, b23code: str, is_group: bool):
    logger.debug(f"b23code: {b23code}")
    message = update.effective_message
    request_url = _api_url + f"/b23/{b23code}"
    if ",av" in message.text or "，av" in message.text:
        request_url += "?av=true"
    if ",iframe" in message.text or "，iframe" in message.text:
        request_url += "?iframe=true"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url=request_url,
        )
        logger.debug(f"resp: {resp.json()}")
        if resp.status_code == 200:
            result = resp.json()["link"]
            if is_group:
                result += f"\n来自 {update.effective_user.name} 发送的 b23 短链接, 已经帮你转换了哦"
            await update.effective_message.reply_text(text=result)


async def _bvav_convert(update: Update, _: ContextTypes, bvavcode: str):
    logger.debug(f"bvavcode: {bvavcode}")
    request_url = _api_url
    if bvavcode.startswith("BV"):
        request_url += f"/bv2av/{bvavcode}"
    elif bvavcode.startswith("av"):
        request_url += f"/av2bv/{bvavcode.removeprefix('av')}"
    else:
        return
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url=request_url,
        )
        logger.debug(f"resp: {resp.json()}")
        if resp.status_code == 200:
            await update.effective_message.reply_text(
                text=resp.json()["link"], quote=True
            )
