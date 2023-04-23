import pytz
from telegram.ext import (
    ApplicationBuilder,
    Defaults,
    PicklePersistence,
    Application,
)

from src.config.config import settings
from src.logger import logger
from src.handlers import handlers


async def init_data(app: Application):
    await app.bot.set_my_commands([("start", "一键猫叫")])
    bot_user = await app.bot.get_me()
    bot_username = bot_user.username
    app.bot_data["bot_username"] = bot_username


def run():
    logger.info("启动bot...")
    token = settings.token
    defaults = Defaults(tzinfo=pytz.timezone("Asia/Shanghai"))
    persistence = PicklePersistence(filepath=settings.pickle_path)

    app = (
        ApplicationBuilder()
        .token(token)
        .persistence(persistence)
        .defaults(defaults)
        .concurrent_updates(True)
        .post_init(init_data)
        .build()
    )
    app.add_handlers(handlers)
    logger.info("Bot已启动")
    app.run_polling()


if __name__ == "__main__":
    run()
