import pyrogram

from kmua import database
from kmua.logger import logger


async def channel_forward_filter_func(_, __, message: pyrogram.types.Message):
    chat = message.chat
    if chat is None:
        return False
    if chat.type not in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    ):
        return False
    if not message.automatic_forward:
        return False
    chat_config = await database.get_chat_config(chat)
    if not chat_config.unpin_channel_pin_enabled:
        return False
    return True


channel_forward_filter = pyrogram.filters.create(channel_forward_filter_func)


# TODO: 队列以防止 floodlimit
@pyrogram.Client.on_message(channel_forward_filter, group=1)
async def unpin_channel(client: pyrogram.Client, message: pyrogram.types.Message):
    try:
        await message.unpin()
    except Exception as e:
        logger.warning(
            f"Failed to unpin message {message.id} in chat {message.chat}: {e.__class__.__name__}:{e}"
        )
