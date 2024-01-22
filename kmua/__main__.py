from pyrogram import Client
from kmua.config import settings, data_dir
from kmua.logger import logger
import kmua.handlers as handlers

client = Client(
    name=settings.session,
    api_id=settings.api_id,
    api_hash=settings.api_hash,
    bot_token=settings.bot_token,
    workdir=data_dir,
)


def main():
    logger.info("Starting bot...")
    client.add_handler(handlers.id_handler)
    client.run()


if __name__ == "__main__":
    main()
