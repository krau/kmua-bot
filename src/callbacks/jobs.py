from telegram.ext import ContextTypes
from ..logger import logger


async def refresh_data(context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["today_waifu"] = {}
    logger.debug("数据已刷新: today_waifu")
