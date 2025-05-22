from pyrogram import Client, idle
from pyrogram.types import BotCommand

from kmua import i18n
from kmua.bot.client import client
from kmua.database import db
from kmua.logger import logger


async def init_bot(client: Client = client):
    logger.info(i18n.t("log.initing", locale="zh-CN"))
    await client.set_bot_commands(
        [
            BotCommand("start", "一键猫叫|召出菜单"),
            BotCommand("waifu", "今日老婆!"),
            BotCommand("waifu_graph", "老婆关系图!"),
            BotCommand("q", "记录语录"),
            BotCommand("d", "删除语录|管理群语录"),
            BotCommand("qrand", "随机语录"),
            BotCommand("t", "获取头衔|互赠头衔"),
            BotCommand("id", "获取聊天ID"),
            BotCommand("ip", "获取IP信息"),
            BotCommand("setu", "随机涩图"),
            BotCommand("config", "更改群组设置"),
            BotCommand("help", "帮助|更多功能"),
        ]
    )


async def main():
    await db.init_db()
    await client.start()
    await init_bot(client)
    await idle()
    await client.stop()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
