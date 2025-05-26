import pyrogram

from kmua import database, i18n


@pyrogram.Client.on_message(pyrogram.filters.command("help"), group=0)
async def help_command(client: pyrogram.Client, message: pyrogram.types.Message):
    """Handle the /help command."""
    chat = message.chat
    user = message.from_user
    in_group = chat.type in (
        pyrogram.enums.ChatType.GROUP,
        pyrogram.enums.ChatType.SUPERGROUP,
    )
    if in_group:
        lang = (await database.get_chat_config(chat.id)).lang
    else:
        lang = (await database.get_user_config(user.id)).lang

    text = i18n.t("bot.msg.help", locale=lang)

    await message.reply_text(text, parse_mode=pyrogram.enums.ParseMode.HTML)
