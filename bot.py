import datetime
import os
from pathlib import Path

import pytz
from telegram import Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
    PicklePersistence,
)

from src.callbacks.jobs import refresh_data
from src.config.config import settings
from src.handlers import handlers, on_error
from src.logger import logger


async def init_data(app: Application):
    await app.bot.set_my_commands(
        [
            ("start", "一键猫叫"),
            ("t", "获取头衔"),
            ("q", "载入史册"),
            ("qrand", "随机名言"),
            ("d", "移出史册"),
            ("c", "清空史册"),
            ("setqp", "设置发名言概率"),
            ("help", "帮助"),
            ("bnhhsh", "不能好好说话!"),
            ("waifu", "今日老婆!"),
        ]
    )
    bot_user = await app.bot.get_me()
    global bot_username
    bot_username = bot_user.username
    app.bot_data["bot_username"] = bot_username
    if not app.bot_data.get("quotes", None):
        app.bot_data["quotes"] = {}
    if not app.bot_data.get("today_waifu", None):
        app.bot_data["today_waifu"] = {}


def run():
    if not os.path.exists(Path(settings.pickle_path).parent):
        os.makedirs(Path(settings.pickle_path).parent)
    token = settings.token
    defaults = Defaults(tzinfo=pytz.timezone("Asia/Shanghai"))
    persistence = PicklePersistence(filepath=settings.pickle_path)
    rate_limiter = AIORateLimiter()
    app = (
        ApplicationBuilder()
        .token(token)
        .persistence(persistence)
        .defaults(defaults)
        .concurrent_updates(True)
        .post_init(init_data)
        .rate_limiter(rate_limiter)
        .build()
    )
    job_queue = app.job_queue
    job_queue.run_daily(
        refresh_data,
        time=datetime.time(4, 0, 0, 0, tzinfo=pytz.timezone("Asia/Shanghai")),
        name="refresh_data",
    )
    app.add_handlers(handlers)
    app.add_error_handler(on_error)
    logger.info("Bot已启动")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
