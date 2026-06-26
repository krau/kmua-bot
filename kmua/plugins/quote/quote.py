import html
import math
import random
import re

import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config

from . import utils


@PyrogramClient.on_message(
    pyrogram.filters.command("q") & pyrogram.filters.group, group=0
)
async def make_quote(client: PyrogramClient, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not chat or not user:
        return
    db_user = await database.upsert_user(user)
    db_chat = await database.upsert_chat(chat)
    if not db_user or not db_chat:
        return
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    cmd = message.command
    if len(cmd) > 1 and cmd[1] != "nopin":
        return
    if not is_explicit_reply(message):
        await message.reply_text(i18n.t("bot.msg.quote.reply_to_required", locale=lang))
        return
    quote_message = message.reply_to_message
    quote_user = common.get_message_origin(quote_message)
    if not quote_user:
        await message.reply_text(i18n.t("bot.msg.quote.origin_not_found", locale=lang))
        return
    db_quote_user = await database.upsert_user(quote_user)
    quote_msg_link = common.get_msg_link(quote_message)
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
    if common.random_chance(app_config.coin_add_chance_for_user_make_quote):
        await database.add_user_coins(db_user.id, 16 * random.randint(1, 9))
    if common.random_chance(app_config.coin_add_chance_for_quote_user):
        await database.add_user_coins(db_quote_user.id, 16 * random.randint(1, 9))


@PyrogramClient.on_message(
    pyrogram.filters.command("qrand") & pyrogram.filters.group, group=0
)
async def random_quote_cmd(client: PyrogramClient, message: pyrogram.types.Message):
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
        else str(quote.user_id)
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


@PyrogramClient.on_message(
    pyrogram.filters.command("qp") & pyrogram.filters.group, group=0
)
async def set_quote_probability(
    client: PyrogramClient, message: pyrogram.types.Message
):
    chat = message.chat
    user = message.sender_chat or message.from_user
    if not user or not chat:
        return
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config:
        return
    if not await common.can_user_manage_bot_in_chat(user, chat):
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
    await message.reply_text(
        i18n.t(
            "bot.msg.group_config_saved",
            locale=chat_config.lang,
        )
    )


@PyrogramClient.on_message(
    pyrogram.filters.command("d") & pyrogram.filters.group, group=0
)
async def delete_quote_in_chat(client: PyrogramClient, message: pyrogram.types.Message):
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    user = message.sender_chat or message.from_user
    is_admin = await common.can_user_manage_bot_in_chat(user, chat)

    quote_link = None
    reply_target = None

    if is_explicit_reply(message) and message.reply_to_message:
        quote_message = message.reply_to_message
        quote_link = common.get_msg_link(quote_message)
        reply_target = quote_message
    elif len(message.command) > 1:
        quote_link = message.command[1]
        reply_target = message
        if not re.match(r"^https?://t.me/.+/\d+$", quote_link, re.IGNORECASE):
            await message.reply_text(
                i18n.t("bot.msg.quote.invalid_link", locale=chat_config.lang)
            )
            return
    else:
        await message.reply_text(
            i18n.t("bot.msg.quote.reply_to_required", locale=chat_config.lang)
        )
        return

    if not quote_link:
        await message.reply_text(
            i18n.t("bot.msg.quote.get_link_failed", locale=chat_config.lang)
        )
        return

    quote = await database.get_quote_by_link(quote_link)
    if not quote:
        await message.reply_text(
            i18n.t("bot.msg.quote.not_found", locale=chat_config.lang)
        )
        return
    if user.id not in (quote.user_id, quote.qer_id):
        if not is_admin:
            await message.reply_text(
                i18n.t("bot.msg.quote.only_delete_self", locale=chat_config.lang)
            )
            return
        result = common.parse_msg_link(quote.link)
        if not result:
            await message.reply_text(
                i18n.t("bot.msg.quote.invalid_link", locale=chat_config.lang)
            )
            return
        quote_chat_id, _ = result
        if quote_chat_id != chat.id:
            await message.reply_text(
                i18n.t("bot.msg.quote.only_delete_or_group", locale=chat_config.lang)
            )
            return

    await database.delete_quote(quote.link)
    await reply_target.reply_text(
        i18n.t("bot.msg.quote.deleted", locale=chat_config.lang)
    )


@PyrogramClient.on_message(
    pyrogram.filters.command("d") & pyrogram.filters.private, group=0
)
async def delete_quote_in_private(
    client: PyrogramClient, message: pyrogram.types.Message
):
    user = message.from_user
    user_config = await database.get_user_config(user.id)
    if len(message.command) < 2:
        await message.reply_text(
            i18n.t("bot.msg.quote.invalid_link", locale=user_config.lang)
        )
        return
    quote_link = message.command[1]
    if not re.match(r"^https?://t.me/.+/\d+$", quote_link, re.IGNORECASE):
        await message.reply_text(
            i18n.t("bot.msg.quote.invalid_link", locale=user_config.lang)
        )
        return
    quote = await database.get_quote_by_link(quote_link)
    if not quote:
        await message.reply_text(
            i18n.t("bot.msg.quote.not_found", locale=user_config.lang)
        )
        return
    result = common.parse_msg_link(quote.link)
    if not result:
        await message.reply_text(
            i18n.t("bot.msg.quote.invalid_link", locale=user_config.lang)
        )
        return
    quote_chat_id, _ = result
    if user.id not in (quote.user_id, quote.qer_id) and not (
        await common.can_user_manage_bot_in_chat(user, quote_chat_id)
    ):
        await message.reply_text(
            i18n.t(
                "bot.msg.quote.only_delete_self_or_admin_in_group",
                locale=user_config.lang,
            )
        )
        return
    await database.delete_quote(quote.link)
    await message.reply_text(i18n.t("bot.msg.quote.deleted", locale=user_config.lang))


@PyrogramClient.on_message(
    ~pyrogram.filters.command("") & pyrogram.filters.group, group=1
)
async def random_quote(client: PyrogramClient, message: pyrogram.types.Message):
    """尝试主动发送引用消息"""
    chat = message.chat
    chat_config = await database.get_chat_config(chat.id)
    pb = chat_config.quote_probability
    if pb <= 0:
        return
    if not common.random_chance(pb):
        return
    quote = await database.get_chat_random_quote(chat.id)
    if not quote:
        return
    user_button_text = (
        quote.user.full_name
        if len(quote.user.full_name) <= 16
        else quote.user.full_name[:16] + "..."
        if quote.user.full_name
        else str(quote.user_id)
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
    if pb <= app_config.coin_add_on_randquote_max_pb and common.random_chance(
        app_config.coin_add_chance_on_randquote
    ):
        await database.add_user_coins(quote.user_id, 16 * random.randint(1, 9))


@PyrogramClient.on_callback_query(pyrogram.filters.regex(r"^user_quote_manage"))
async def user_quote_manage(
    client: PyrogramClient, query: pyrogram.types.CallbackQuery
):
    user = query.from_user
    data = str(query.data)
    user_config = await database.get_user_config(user)
    lang = user_config.lang
    page = int(data.split(" ")[-1]) if len(data.split(" ")) > 1 else 1
    page_size = 5
    count = await database.get_user_quote_count(user.id)
    max_page = math.ceil(count / page_size)
    if count == 0:
        text = (
            i18n.t("bot.msg.quote.user_all_deleted", locale=lang)
            if "delete_user_quote" in data
            else i18n.t("bot.msg.quote.user_no_quote", locale=lang)
        )
        await query.edit_message_text(
            text,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            i18n.t("bot.button.back", locale=lang),
                            callback_data="back_home",
                        )
                    ]
                ]
            ),
        )
        return
    if page > max_page or page < 1:
        await query.answer(
            i18n.t("bot.msg.quote.page_invalid", locale=lang),
            show_alert=True,
        )
        return
    text = (
        i18n.t("bot.msg.quote.user_quote_list_head", locale=lang).format(
            count=count,
            page=page,
            max_page=max_page,
        )
        + "\n"
    )
    quotes = await database.get_user_quotes_page(user.id, page, page_size)
    keyboard, line = [], []
    for index, quote in enumerate(quotes):
        quote_content = (
            html.escape(quote.text[:100])
            if quote.text
            else i18n.t("bot.msg.quote.no_text", locale=lang)
        )
        text += f"{index + 1}. <a href={quote.link}>{quote_content}</a>\n\n"

        line.append(
            pyrogram.types.InlineKeyboardButton(
                text=f"{index + 1}",
                callback_data=f"delete_user_quote {quote.link} {str(page)}",
            )
        )
    keyboard.append(line)
    # keyboard.append(qer_quote_manage_button) TODO
    keyboard.append(
        [
            pyrogram.types.InlineKeyboardButton(
                i18n.t("bot.button.page_prev", locale=lang),
                callback_data=f"user_quote_manage {page - 1}",
            ),
            pyrogram.types.InlineKeyboardButton(
                i18n.t("bot.button.back", locale=lang),
                callback_data="back_home",
            ),
            pyrogram.types.InlineKeyboardButton(
                i18n.t("bot.button.page_next", locale=lang),
                callback_data=f"user_quote_manage {page + 1}",
            ),
        ]
    )
    await query.edit_message_text(
        text,
        parse_mode=pyrogram.enums.ParseMode.HTML,
        reply_markup=pyrogram.types.InlineKeyboardMarkup(keyboard),
    )


@PyrogramClient.on_callback_query(pyrogram.filters.regex(r"^delete_user_quote"))
async def delete_user_quote(
    client: PyrogramClient, query: pyrogram.types.CallbackQuery
):
    user = query.from_user
    data = str(query.data)
    user_config = await database.get_user_config(user)
    lang = user_config.lang
    parts = data.split(" ")
    quote_link = parts[1]
    await database.delete_quote(quote_link)
    await query.answer(
        i18n.t("bot.msg.quote.deleted", locale=lang),
    )
    await user_quote_manage(
        client,
        query,
    )
