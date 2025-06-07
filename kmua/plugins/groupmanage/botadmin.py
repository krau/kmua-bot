import pyrogram

from kmua import common, database, enums, i18n


@pyrogram.Client.on_message(
    (pyrogram.filters.command("botpromote") | pyrogram.filters.command("botdemote"))
    & pyrogram.filters.group,
    group=0,
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
    if not message.command:
        return
    try:
        target_user_id = (
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
    if not target_user_id or target_user_id in (
        enums.ChatID.FAKE_CHANNEL,
        enums.ChatID.SERVICE_CHAT,
        enums.ChatID.ANONYMOUS_ADMIN,
        user.id,
    ):
        await message.reply(
            i18n.t("bot.msg.botadmin.invalid_user", locale=chat_config.lang)
        )
        return
    demote = message.command[0] == "botdemote"
    user_association = await database.get_association(user.id, chat.id)
    if (
        not user_association
        or not user_association.is_bot_admin
        or (
            user_association.promoted_by is not None
            and user_association.promoted_by == target_user_id
        )
    ):
        await message.reply(
            i18n.t("bot.msg.botadmin.target_is_upstream", locale=chat_config.lang)
        )
        return
    db_user = await database.get_user_by_id(target_user_id)
    if not db_user:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_not_found", locale=chat_config.lang)
        )
        return
    if db_user.is_bot:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_is_bot", locale=chat_config.lang)
        )
        return
    association = await database.get_association(db_user.id, chat.id)
    if not association:
        await message.reply(
            i18n.t("bot.msg.botadmin.user_not_in_chat", locale=chat_config.lang)
        )
        return
    if association.is_bot_admin == (not demote):
        await message.reply(
            i18n.t(
                "bot.msg.botadmin.already_set",
                locale=chat_config.lang,
            )
        )
        return
    association.is_bot_admin = False if demote else True
    association.promoted_by = user.id if not demote else None
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
