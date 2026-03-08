import pyrogram
from pyrogram.client import Client

from kmua import database
from kmua.config import app_config, reload_config
from kmua.logger import logger


@Client.on_message(pyrogram.filters.command("reload"), group=0)
async def reload_command(client: Client, message: pyrogram.types.Message):
    user = message.from_user
    if user is None:
        return
    db_user = await database.get_user_by_id(user.id)
    if not db_user:
        return
    if not db_user.is_bot_global_admin and user.id not in app_config.owners:
        await message.reply_text("Permission denied")
        return

    success, msg, changed = reload_config()
    if success and changed:
        logger.info(
            f"Config reloaded by {user.id}, changed fields: {', '.join(changed)}"
        )
        msg += f"\n\nChanged fields ({len(changed)}): {', '.join(changed)}"
    elif success:
        msg += "\n\nNo fields changed"
    await message.reply_text(msg)
