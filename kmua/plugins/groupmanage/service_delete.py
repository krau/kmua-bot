import pyrogram

from kmua import database
from kmua.logger import logger


@pyrogram.Client.on_message(pyrogram.filters.service & pyrogram.filters.group, group=1)
async def delete_service_message(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    chat = message.chat
    if chat is None:
        return
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config.delete_events_enabled:
        return
    if message.service:
        try:
            await message.delete()
        except Exception as e:
            # TODO: cache bot has no permission to delete messages
            logger.error(
                f"Failed to delete service message {message.id} in chat {chat.id}: {e.__class__.__name__}:{e}"
            )
