from pyrogram import idle

from kmua.bot.client import client
from kmua.database import db


async def main():
    await db.init_db()
    await client.start()
    await idle()
    await client.stop()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
