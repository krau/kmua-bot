import math
import re

import pyrogram

from kmua import common, database, i18n

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
        text += f"\n {i18n.t('bot.msg.quote.text_not_available', locale=lang)}"
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
async def random_quote_cmd(client: pyrogram.Client, message: pyrogram.types.Message):
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    if chat_config.quote_probability <= 0:
        return
    quote = await database.get_chat_random_quote(chat.id)
    if not quote:
        await message.reply_text(
            i18n.t("bot.msg.quote.chat_no_quote", locale=chat_config.lang)
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


@pyrogram.Client.on_message(
    pyrogram.filters.command("qp") & pyrogram.filters.group, group=0
)
async def set_quote_probability(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config:
        return
    if not await common.can_user_manage_bot_in_chat(message.from_user, chat):
        await message.reply_text(
            i18n.t("bot.msg.no_permission_group", locale=chat_config.lang)
        )
        return
    if len(message.command) < 2:
        await message.reply_text(
            i18n.t("bot.msg.quote.probability_usage", locale=chat_config.lang)
        )
        return
    if not re.compile(
        r"""
^
[+-]?                # optional sign
(                    # group:
  \d+(\.\d*)?        # e.g., 123 or 123. or 123.45
  |\.\d+             # or .456
)
([eE][+-]?\d+)?      # optional exponent
$
""",
        re.VERBOSE,
    ).match(message.command[1]):
        await message.reply_text(
            i18n.t("bot.msg.quote.probability_invalid", locale=chat_config.lang)
        )
        return
    try:
        qp = float(message.command[1])
        if math.isnan(qp) or math.isinf(qp):
            raise ValueError("Invalid probability value")
    except ValueError:
        await message.reply_text(
            i18n.t("bot.msg.quote.probability_invalid", locale=chat_config.lang)
        )
        return
    if qp > 1:
        qp = 1.0
    elif qp < 0:
        qp = -1.0
    chat_config.quote_probability = qp
    await database.update_chat_config(chat=chat, config=chat_config)


@pyrogram.Client.on_message(
    pyrogram.filters.command("d") & pyrogram.filters.group, group=0
)
async def delete_quote_in_chat(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    user = message.sender_chat or message.from_user
    is_admin = await common.can_user_manage_bot_in_chat(user, chat)
    if not message.reply_to_message:
        await message.reply_text(
            i18n.t("bot.msg.quote.reply_to_required", locale=chat_config.lang)
        )
        return
    quote_message = message.reply_to_message
    quote_msg_link = utils.get_msg_link(quote_message)
    if not quote_msg_link:
        await message.reply_text(
            i18n.t("bot.msg.quote.get_link_failed", locale=chat_config.lang)
        )
        return
    quote = await database.get_quote_by_link(quote_msg_link)
    if not quote:
        await message.reply_text(
            i18n.t("bot.msg.quote.not_found", locale=chat_config.lang)
        )
        return
    if user.id not in (quote.user_id, quote.qer_id) and not is_admin:
        await message.reply_text(
            i18n.t("bot.msg.quote.only_delete_self", locale=chat_config.lang)
        )
        return
    await database.delete_quote(quote.link)
    await quote_message.reply_text(
        i18n.t("bot.msg.quote.deleted", locale=chat_config.lang)
    )


@pyrogram.Client.on_message(
    ~pyrogram.filters.command("") & pyrogram.filters.group, group=1
)
async def random_quote(client: pyrogram.Client, message: pyrogram.types.Message):
    """尝试主动发送引用消息"""
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    pb = chat_config.quote_probability
    if pb <= 0:
        return
    if not utils.random_chance(pb):
        return
    quote = await database.get_chat_random_quote(chat.id)
    if not quote:
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
