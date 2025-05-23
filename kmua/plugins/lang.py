import pyrogram
from kmua import common
from kmua.i18n import i18n

locales = i18n.get_available_locales()
lang_markup = pyrogram.types.InlineKeyboardMarkup(
    [
        [
            pyrogram.types.InlineKeyboardButton(
                i18n.t("bot.button.lang", locale=locale),
                callback_data=f"lang/{locale}",
            )
            for locale in locales
        ]
    ]
)


@pyrogram.Client.on_message(
    pyrogram.filters.command("lang") & pyrogram.filters.private, group=0
)
async def change_user_lang(client: pyrogram.Client, message: pyrogram.types.Message):
    await message.reply(
        text="Choose the language you want to use",
        reply_markup=lang_markup,
    )


@pyrogram.Client.on_message(
    pyrogram.filters.command("lang") & pyrogram.filters.group, group=0
)
async def change_group_lang(client: pyrogram.Client, message: pyrogram.types.Message):
    if not await common.can_user_manage_bot_in_chat(message.from_user, message.chat):
        return
    await message.reply(
        text="Choose the language you want to use",
        reply_markup=lang_markup,
    )
