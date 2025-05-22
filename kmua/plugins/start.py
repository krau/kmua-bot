from pyrogram import Client, filters
from pyrogram.types import Message


@Client.on_message(filters.command("start"), group=0)
async def start(client: Client, message: Message):
    await message.reply("Hello! I am a bot. How can I assist you today?")
