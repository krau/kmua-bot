import uvloop
from pyrogram import Client

from kmua.config import data_dir, settings
from kmua.handlers import kmua_handlers as handlers
from kmua.logger import logger

uvloop.install()

client = Client(
    name=settings.session,
    api_id=settings.api_id,
    api_hash=settings.api_hash,
    bot_token=settings.bot_token,
    workdir=data_dir,
)


def main():
    logger.info("Starting bot...")
    for group, handler_list in handlers.items():
        for handler in handler_list:
            client.add_handler(handler, group=group)

    client.run()


if __name__ == "__main__":
    main()
