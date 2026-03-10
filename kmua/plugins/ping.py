import time

from pyrogram import filters
from pyrogram.client import Client
from pyrogram.types import Message


@Client.on_message(filters.command("ping"), group=0)
async def ping(client: Client, message: Message):
    t0 = time.monotonic()
    sent = await message.reply("Pong!")
    ms = (time.monotonic() - t0) * 1000
    await sent.edit(f"Pong! | {ms:.3f}ms")
