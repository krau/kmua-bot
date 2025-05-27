import pyrogram

from kmua import common


@pyrogram.Client.on_message(pyrogram.filters.command("id"), group=0)
async def getchatid(client: pyrogram.client, message: pyrogram.types.Message):
    chat = message.chat
    user = message.sender_chat or message.from_user
    if target_msg := message.reply_to_message:
        target = common.get_message_origin(target_msg)
        await message.reply_text(
            f"This Chat ID: `{chat.id}`\n"
            f"Replied User ID: `{target.id}`\n"
            f"Your User ID: `{user.id}`\n"
        )
    else:
        await message.reply_text(
            f"This Chat ID: `{chat.id}`\nYour User ID: `{user.id}`\n"
        )
