from pyrogram import Client
from kmua.config import settings, data_dir
from kmua.logger import logger
from kmua.handlers import command_handlers

client = Client(
    name=settings.session,
    api_id=settings.api_id,
    api_hash=settings.api_hash,
    bot_token=settings.bot_token,
    workdir=data_dir,
)

def main():
    logger.info("Starting bot...")
    for handler in command_handlers:
        client.add_handler(handler, 0)
    client.run()


if __name__ == "__main__":
    main()
