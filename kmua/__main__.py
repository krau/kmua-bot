import uvloop
from pyrogram import Client

from kmua.config import data_dir, settings
from kmua.handlers import kmua_handlers as handlers
from kmua.logger import logger

logger.debug("test")

uvloop.install()

def main():
    client = Client(
        name=settings.session,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        bot_token=settings.bot_token,
        workdir=data_dir,
    )

    logger.debug("Registering handlers...")
    for group, handler_list in handlers.items():
        for handler in handler_list:
            client.add_handler(handler, group=group)
    logger.info("Bot started")
    client.run()


if __name__ == "__main__":
    main()
