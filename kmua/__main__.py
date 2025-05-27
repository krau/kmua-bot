import asyncio

from pyrogram import Client, idle
from pyrogram.types import BotCommand

from kmua import common, database, i18n
from kmua.bot import jobs
from kmua.bot.client import client
from kmua.config import app_config
from kmua.database import db
from kmua.logger import logger


@client.on_start()
async def init_bot(client: Client = client):
    logger.info(i18n.t("log.initing", locale=app_config.lang))
    if not app_config.avatar_cache_dir.exists():
        app_config.avatar_cache_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(i18n.t("log.getting_me", locale=app_config.lang))
    me = await client.get_me()
    await database.upsert_user(me)
    logger.debug(i18n.t("log.setting_commands", locale=app_config.lang))
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
            BotCommand("qp", i18n.t("bot.cmd.qp", locale=app_config.lang)),
            BotCommand("t", i18n.t("bot.cmd.t", locale=app_config.lang)),
            BotCommand("sett", i18n.t("bot.cmd.sett", locale=app_config.lang)),
            BotCommand("id", i18n.t("bot.cmd.id", locale=app_config.lang)),
            BotCommand("ip", i18n.t("bot.cmd.ip", locale=app_config.lang)),
            BotCommand("setu", i18n.t("bot.cmd.setu", locale=app_config.lang)),
            BotCommand("config", i18n.t("bot.cmd.config", locale=app_config.lang)),
            BotCommand("greet", i18n.t("bot.cmd.greet", locale=app_config.lang)),
            BotCommand("help", i18n.t("bot.cmd.help", locale=app_config.lang)),
        ]
    )
    common.jobqueue.add_daily_job("cleanup", jobs.cleanup, hour=4)
    common.jobqueue.start()
    logger.success(i18n.t("log.inited", locale=app_config.lang))


@client.on_stop()
async def stop_bot(client: Client = client):
    logger.info(i18n.t("log.stopping", locale=app_config.lang))
    common.jobqueue.shutdown()
    await db.close_db()
    logger.success(i18n.t("log.exit", locale=app_config.lang))


async def main():
    await db.init_db()
    await client.start()
    await idle()
    await client.stop()  # type: ignore


def exception_handler(loop, context):
    msg = context.get("exception") or context.get("message")
    logger.error(f"[GLOBAL EXCEPTION] {msg!r}")


if __name__ == "__main__":
    client.loop.set_exception_handler(exception_handler)
    client.loop.run_until_complete(main())
