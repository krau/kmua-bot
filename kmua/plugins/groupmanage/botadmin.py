import pyrogram

from kmua import common, database, enums, i18n


@pyrogram.Client.on_message(
    pyrogram.filters.command("botpromote") & pyrogram.filters.group, group=0
)
async def set_user_bot_admin_in_chat(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not chat or not user:
        return
    chat_config = await database.get_chat_config(chat)
    if not await common.can_user_manage_bot_in_chat(user, chat):
        await message.reply(
            i18n.t("bot.msg.no_permission_group", locale=chat_config.lang)
        )
        return
    try:
        to_promote_user_id = (
            (
                message.reply_to_message.sender_chat
                or message.reply_to_message.from_user
            ).id
            if message.reply_to_message
            else int(message.command[1])
            if (len(message.command) > 1 and message.command[1].isdigit())
            else None
        )
    except (ValueError, IndexError):
        await message.reply(
            i18n.t("bot.msg.botadmin.invalid_user", locale=chat_config.lang)
        )
        return
    if not to_promote_user_id or to_promote_user_id in (
        enums.ChatID.FAKE_CHANNEL,
        enums.ChatID.SERVICE_CHAT,
        enums.ChatID.ANONYMOUS_ADMIN,
        user.id,
    ):
        await message.reply(
            i18n.t("bot.msg.botadmin.invalid_user", locale=chat_config.lang)
        )
        return
    db_user = await database.get_user_by_id(to_promote_user_id)
    if not db_user:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_not_found", locale=chat_config.lang)
        )
        return
    if not db_user.is_real_user:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_not_real", locale=chat_config.lang)
        )
        return
    association = await database.get_association(db_user.id, chat.id)
    if not association:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_not_in_chat", locale=chat_config.lang)
        )
        return
    association.is_bot_admin = not association.is_bot_admin
    await database.update_association(association)
    await message.reply(
        i18n.t(
            "bot.msg.botadmin.success",
            locale=chat_config.lang,
        ).format(
            user=db_user.full_name,
            status=association.is_bot_admin,
        )
    )
