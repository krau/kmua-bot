import pyrogram

from kmua import database
from kmua.config import app_config


@pyrogram.Client.on_message(pyrogram.filters.command("status"), group=0)
async def status_command(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.from_user
    if user is None:
        return
    db_user = await database.get_user_by_id(user.id)
    if not db_user.is_bot_global_admin and user.id not in app_config.owners:
        return
    count_users = await database.count_users()
    count_chats = await database.count_chats()
    count_quotes = await database.count_quotes()
    count_associations = await database.count_associations()
    count_bottles = await database.count_bottles()
    affection_stats = await database.get_affection_stats()
    await message.reply_text(
        f"users: {count_users}\n"
        f"chats: {count_chats}\n"
        f"quotes: {count_quotes}\n"
        f"associations: {count_associations}\n"
        f"bottles: {count_bottles}\n"
        f"affection stats: {affection_stats}",
    )
