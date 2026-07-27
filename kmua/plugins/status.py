import pyrogram

from kmua import database
from kmua.common import ops
from kmua.config import app_config


@pyrogram.Client.on_message(pyrogram.filters.command("status"), group=0)
async def status_command(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.from_user
    if user is None:
        return
    db_user = await database.get_user_by_id(user.id)
    if not db_user.is_bot_global_admin and user.id not in app_config.owners:
        return
    stats = await ops.collect_stats()
    await message.reply_text(
        f"users: {stats['users']}\n"
        f"chats: {stats['chats']}\n"
        f"quotes: {stats['quotes']}\n"
        f"associations: {stats['associations']}\n"
        f"bottles: {stats['bottles']}\n"
        f"affection stats: {stats['affection']}",
    )
