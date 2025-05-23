import pyrogram
from kmua import common, database
from kmua.i18n import i18n

locales = i18n.get_available_locales()
lang_markup = pyrogram.types.InlineKeyboardMarkup(
    [
        [
            pyrogram.types.InlineKeyboardButton(
                locale,
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
        text="Choose the language this chat want to use",
        reply_markup=lang_markup,
    )


@pyrogram.Client.on_callback_query(pyrogram.filters.regex("^lang/"))
async def change_lang(
    client: pyrogram.Client, callback_query: pyrogram.types.CallbackQuery
):
    select_lang = callback_query.data.split("/")[1]
    if callback_query.message.chat.type == pyrogram.enums.ChatType.PRIVATE:
        config = await database.get_user_config(callback_query.from_user)
        config.lang = select_lang
        await database.update_user_config(callback_query.from_user.id, config)
    else:
        if not await common.can_user_manage_bot_in_chat(
            callback_query.from_user, callback_query.message.chat
        ):
            await callback_query.answer(
                text=i18n.t("bot.msg.no_permission_group", locale=select_lang),
                show_alert=True,
                cache_time=10,
            )
            return
        config = await database.get_chat_config(callback_query.message.chat)
        config.lang = select_lang
        await database.update_chat_config(callback_query.message.chat, config)
    await callback_query.edit_message_text(
        text=i18n.t("bot.msg.lang_changed", locale=select_lang).format(lang=select_lang)
    )
