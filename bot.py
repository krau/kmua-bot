import datetime
from pathlib import Path

import pytz
from telegram.constants import UpdateType
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
    PicklePersistence,
)

from src.callbacks.jobs import refresh_data
from src.config.config import settings,avatars_dir
from src.handlers import handlers, on_error
from src.logger import logger


async def init_data(app: Application):
    await app.bot.set_my_commands(
        [
            ("start", "一键猫叫"),
            ("t", "获取头衔"),
            ("sett", "修改/t赋予权限"),
            ("waifu", "今日老婆!"),
            ("waifu_graph", "老婆关系图！"),
            ("q", "载入史册"),
            ("clear_chat_quote", "清空史册"),
            ("setqp", "设置发名言概率"),
            ("help", "帮助"),
            ("qrand", "随机名言"),
            ("d", "移出史册"),
            ("set_greet", "设置入群欢迎"),
            ("id", "获取聊天ID"),
            ("clear_chat_data", "⚠清空聊天数据"),
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
    app.bot_data["waifu_mutex"] = {}
    if not app.bot_data.get("user_info"):
        app.bot_data["user_info"] = {}
    if not app.bot_data.get("music"):
        app.bot_data["music"] = []
    if not app.bot_data.get("sticker2img"):
        app.bot_data["sticker2img"] = {}


def run():
    if not Path(settings.pickle_path).parent.exists():
        Path(settings.pickle_path).parent.mkdir()
    if not avatars_dir.exists():
        avatars_dir.mkdir()
    token = settings.token
    defaults = Defaults(tzinfo=pytz.timezone("Asia/Shanghai"))
    persistence = PicklePersistence(
        filepath=settings.pickle_path,
        update_interval=settings.get("pickle_update_interval", 60),
    )
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
    allowed_updates = [
        UpdateType.MESSAGE,
        UpdateType.CALLBACK_QUERY,
        UpdateType.CHAT_MEMBER,
        UpdateType.MY_CHAT_MEMBER,
        UpdateType.CHOSEN_INLINE_RESULT,
        UpdateType.INLINE_QUERY,
    ]
    app.run_polling(allowed_updates=allowed_updates, drop_pending_updates=True)


if __name__ == "__main__":
    run()
