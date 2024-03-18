import datetime

import pytz
import uvloop
from telegram.constants import UpdateType
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
)

import kmua.dao._db as db
from kmua.callbacks.jobs import clean_data
from kmua.config import settings
from kmua.handlers import (
    callback_query_handlers,
    chatdata_handlers,
    command_handlers,
    message_handlers,
    on_error,
    other_handlers,
)
from kmua.logger import logger


async def init_data(app: Application):
    """
    初始化数据
    """
    logger.info("initing...")
    await app.bot.set_my_commands(
        [
            ("start", "一键猫叫|召出菜单"),
            ("waifu", "今日老婆!"),
            ("waifu_graph", "老婆关系图！"),
            ("q", "载入史册"),
            ("d", "移出史册"),
            ("t", "获取头衔|互赠头衔"),
            ("help", "帮助|更多功能"),
            ("qrand", "随机语录"),
            ("set_greet", "设置入群欢迎"),
            ("id", "获取聊天ID"),
        ]
    )
    logger.success("started bot")


async def stop(_: Application):
    """
    关闭数据库连接
    """
    logger.debug("close database connection...")
    db.commit()
    db.close()
    logger.success("stopped bot")


def run():
    """
    启动bot
    """
    uvloop.install()
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
        clean_data,
        time=datetime.time(4, 0, 0, 0, tzinfo=pytz.timezone("Asia/Shanghai")),
        name="refresh_waifu_data",
    )
    app.add_handlers(
        {
            0: command_handlers,
            1: message_handlers,
            2: chatdata_handlers,
            3: callback_query_handlers,
            4: other_handlers,
        }
    )
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
