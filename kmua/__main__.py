import datetime
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import uvloop
from telegram.constants import UpdateType
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
    PersistenceInput,
    PicklePersistence,
)

import kmua.dao._db as db
from kmua.callbacks.jobs import clean_data
from kmua.config import settings
from kmua.handlers import (
    callback_query_handlers,
    chatdata_handlers,
    command_handlers,
    inline_query_handler_group,
    message_handlers,
    on_error,
)
from kmua.logger import logger
from kmua.middlewares import after_middleware, before_middleware


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "ok", "message": "kmua is running"}).encode("utf-8")
        )

    def log_message(self, format, *args):
        return


def run_server():
    server_address = (
        settings.get("health_check_host", "0.0.0.0"),
        settings.get("health_check_port", 39848),
    )
    httpd = HTTPServer(server_address, HealthCheckHandler)
    httpd.serve_forever()


async def init_data(app: Application):
    logger.info("initing commands")
    await app.bot.set_my_commands(
        [
            ("start", "一键猫叫|召出菜单"),
            ("waifu", "今日老婆!"),
            ("waifu_graph", "老婆关系图!"),
            ("q", "记录语录"),
            ("d", "删除语录|管理群语录"),
            ("qrand", "随机语录"),
            ("t", "获取头衔|互赠头衔"),
            ("id", "获取聊天ID"),
            ("ip", "获取IP信息"),
            ("setu", "随机涩图"),
            ("config", "更改群组设置"),
            ("help", "帮助|更多功能"),
        ]
    )
    logger.success("started bot")


async def stop(app: Application):
    logger.debug("close database connection...")
    db.commit()
    db.close()
    logger.debug("flush persistence...")
    await app.persistence.flush()
    logger.success("stopped bot")


def run_bot():
    """
    启动bot
    """
    uvloop.install()
    token = settings.token
    defaults = Defaults(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    rate_limiter = AIORateLimiter()
    persistence_input = PersistenceInput(
        bot_data=True, chat_data=True, user_data=False, callback_data=False
    )
    pickle_persistence = PicklePersistence(
        filepath="data/persistence.pickle", on_flush=True, store_data=persistence_input
    )
    app = (
        ApplicationBuilder()
        .token(token)
        .defaults(defaults)
        .concurrent_updates(True)
        .post_init(init_data)
        .post_stop(stop)
        .rate_limiter(rate_limiter)
        .base_url(settings.get("base_url", "https://api.telegram.org/bot"))
        .base_file_url(
            settings.get("base_file_url", "https://api.telegram.org/file/bot")
        )
        .persistence(pickle_persistence)
        .build()
    )
    job_queue = app.job_queue
    job_queue.run_daily(
        clean_data,
        time=datetime.time(
            4,
            0,
            0,
            0,
            datetime.timezone(datetime.timedelta(hours=8)),
        ),
        name="clean_data",
    )
    app.add_handlers(
        {
            -1: before_middleware,
            0: command_handlers,
            1: message_handlers,
            2: chatdata_handlers,
            3: callback_query_handlers,
            4: inline_query_handler_group,
            100: after_middleware,
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
        UpdateType.EDITED_MESSAGE,
    ]
    if settings.get("webhook"):
        logger.info("running webhook...")
        app.run_webhook(
            listen=settings.listen,
            port=settings.port,
            secret_token=settings.secret_token,
            url_path=settings.get("url_path", ""),
            key=settings.get("key"),
            cert=settings.get("cert"),
            webhook_url=settings.webhook_url,
            allowed_updates=allowed_updates,
            drop_pending_updates=settings.get("drop_pending_updates", False),
        )
    else:
        app.run_polling(
            allowed_updates=allowed_updates,
            drop_pending_updates=settings.get("drop_pending_updates", False),
            close_loop=False,
        )


if __name__ == "__main__":
    if settings.get("health_check_enable"):
        logger.info("running health check server...")
        threading.Thread(target=run_server, daemon=True).start()
    run_bot()
