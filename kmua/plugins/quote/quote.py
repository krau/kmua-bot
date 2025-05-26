import pyrogram

from kmua import database, i18n

from . import utils


@pyrogram.Client.on_message(
    pyrogram.filters.command("q") & pyrogram.filters.group, group=0
)
async def make_quote(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    chat = message.chat
    db_user = await database.upsert_user(user)
    db_chat = await database.upsert_chat(chat)
    if not db_user or not db_chat:
        return
    chat_config = await database.get_chat_config(chat.id)
    lang = chat_config.lang
    cmd = message.command
    if len(cmd) > 1 and cmd[1] != "nopin":
        return
    if not message.reply_to_message:
        await message.reply_text(i18n.t("bot.msg.quote.reply_to_required", locale=lang))
        return
    if message.topic_message:
        await message.reply_text(
            i18n.t("bot.msg.quote.topic_not_supported", locale=lang)
        )
        return
    quote_message = message.reply_to_message
    quote_user = utils.get_message_origin(quote_message)
    if not quote_user:
        await message.reply_text(i18n.t("bot.msg.quote.origin_not_found", locale=lang))
        return
    db_quote_user = await database.upsert_user(quote_user)
    quote_msg_link = utils.get_msg_link(quote_message)
    if not quote_msg_link:
        await message.reply_text(i18n.t("bot.msg.quote.get_link_failed", locale=lang))
        return
    if (await database.get_quote_by_link(quote_msg_link)) is not None:
        await message.reply_text(i18n.t("bot.msg.quote.already_exists", locale=lang))
        return
    text = i18n.trl("bot.msg.quote.created", locale=lang)
    if not quote_message.text or len(quote_message.text) > 200:
        text += i18n.t("bot.msg.quote.text_not_available", locale=lang)
    await quote_message.reply_text(text, parse_mode=pyrogram.enums.ParseMode.HTML)
    quote_img = await utils.send_quote(client, chat.id, quote_message, quote_user)
    if not (len(cmd) > 1 and cmd[1] == "nopin") and chat_config.quote_pin_message:
        try:
            await quote_message.pin(disable_notification=True)
        except:
            pass
    await database.add_quote(
        chat=db_chat,
        user=db_quote_user,
        qer=db_user,
        link=quote_msg_link,
        message_id=quote_message.id,
        text=quote_message.text,
        img=quote_img,
    )


@pyrogram.Client.on_message(
    pyrogram.filters.command("qrand") & pyrogram.filters.group, group=0
)
async def random_quote(client: pyrogram.Client, message: pyrogram.types.Message):
    chat = message.chat
    quote = await database.get_chat_random_quote(chat.id)
    if not quote:
        await message.reply_text(
            i18n.t("bot.msg.quote.chat_no_quote", locale=chat.lang)
        )
        return
    user_button_text = (
        quote.user.full_name
        if len(quote.user.full_name) <= 16
        else quote.user.full_name[:16] + "..."
        if quote.user.full_name
        else quote.user_id
    )
    await client.copy_message(
        chat_id=chat.id,
        from_chat_id=quote.chat_id,
        message_id=quote.message_id,
        message_thread_id=message.message_thread_id,
        reply_markup=pyrogram.types.InlineKeyboardMarkup(
            [[pyrogram.types.InlineKeyboardButton(user_button_text, url=quote.link)]]
        ),
    )
