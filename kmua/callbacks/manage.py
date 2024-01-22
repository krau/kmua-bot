from pyrogram import Client, types
from kmua.logger import logger
from kmua import common

async def init(client: Client, message: types.Message):
    user = message.sender_chat or message.from_user
    if not common.verify_user_can_manage_bot(user):
        return
    logger.info("Init Bot")
    await client.set_bot_commands(
        [
            types.BotCommand("help", "帮助"),
            types.BotCommand("id", "获取ID"),
        ]
    )
    await message.reply_text("Bot init success!")
