from pyrogram import Client, idle
from pyrogram.types import BotCommand

from kmua import i18n
from kmua.bot.client import client
from kmua.config import app_config
from kmua.database import db
from kmua.logger import logger


async def init_bot(client: Client = client):
    logger.info(i18n.t("log.initing", locale=app_config.lang))
    await client.set_bot_commands(
        [
            BotCommand(
                "start",
                i18n.t("bot.cmd.start", locale=app_config.lang),
            ),
            BotCommand("waifu", i18n.t("bot.cmd.waifu", locale=app_config.lang)),
            BotCommand(
                "waifu_graph", i18n.t("bot.cmd.waifu_graph", locale=app_config.lang)
            ),
            BotCommand("q", i18n.t("bot.cmd.q", locale=app_config.lang)),
            BotCommand("d", i18n.t("bot.cmd.d", locale=app_config.lang)),
            BotCommand("qrand", i18n.t("bot.cmd.qrand", locale=app_config.lang)),
            BotCommand("t", i18n.t("bot.cmd.t", locale=app_config.lang)),
            BotCommand("id", i18n.t("bot.cmd.id", locale=app_config.lang)),
            BotCommand("ip", i18n.t("bot.cmd.ip", locale=app_config.lang)),
            BotCommand("setu", i18n.t("bot.cmd.setu", locale=app_config.lang)),
            BotCommand("config", i18n.t("bot.cmd.config", locale=app_config.lang)),
            BotCommand("help", i18n.t("bot.cmd.help", locale=app_config.lang)),
        ]
    )
    logger.success(i18n.t("log.inited", locale=app_config.lang))


async def main():
    await db.init_db()
    await client.start()
    await init_bot(client)
    await idle()
    await client.stop()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
