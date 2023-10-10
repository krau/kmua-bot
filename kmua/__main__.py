import datetime

import pytz
from telegram.constants import UpdateType
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
)
from kmua.logger import logger
from kmua.config import settings
import kmua.dao._db as db
from kmua.handlers import handlers, on_error
from kmua.callbacks.jobs import refresh_waifu_data


async def init_data(app: Application):
    logger.info("initing...")
    await app.bot.set_my_commands(
        [
            ("start", "一键猫叫|召出菜单"),
            ("waifu", "今日老婆!"),
            ("waifu_graph", "老婆关系图！"),
            ("q", "载入史册"),
            ("d", "移出史册"),
            ("t", "获取头衔|互赠头衔"),
            ("help", "帮助"),
            ("qrand", "随机语录"),
            ("setqp", "设置主动发送语录概率"),
            ("sett", "修改/t赋予权限"),
            ("set_greet", "设置入群欢迎"),
            ("id", "获取聊天ID"),
        ]
    )
    logger.success("started bot")


async def stop(app: Application):
    logger.debug("close database connection...")
    db.commit()
    db.close()
    logger.success("stopped bot")


def run():
    token = settings.token
    defaults = Defaults(tzinfo=pytz.timezone("Asia/Shanghai"))
    rate_limiter = AIORateLimiter()
    app = (
        ApplicationBuilder()
        .token(token)
        .defaults(defaults)
        .concurrent_updates(True)
        .post_init(init_data)
        .post_stop(stop)
        .rate_limiter(rate_limiter)
        .build()
    )
    job_queue = app.job_queue
    job_queue.run_daily(
        refresh_waifu_data,
        time=datetime.time(4, 0, 0, 0, tzinfo=pytz.timezone("Asia/Shanghai")),
        name="refresh_waifu_data",
    )
    app.add_handlers(handlers)
    app.add_error_handler(on_error)
    allowed_updates = [
        UpdateType.MESSAGE,
        UpdateType.CALLBACK_QUERY,
        UpdateType.CHAT_MEMBER,
        UpdateType.MY_CHAT_MEMBER,
        UpdateType.CHOSEN_INLINE_RESULT,
        UpdateType.INLINE_QUERY,
    ]
    app.run_polling(
        allowed_updates=allowed_updates, drop_pending_updates=True, close_loop=False
    )


run()
