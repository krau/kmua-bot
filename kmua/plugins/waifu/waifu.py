import html
from io import BytesIO

import pyrogram
import pyrogram.errors
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, enums, i18n
from kmua.database.models import ChatData, UserData
from kmua.logger import logger

from . import utils


@PyrogramClient.on_message(
    pyrogram.filters.command("waifu") & pyrogram.filters.group, group=0
)
async def today_waifu(client: PyrogramClient, message: pyrogram.types.Message):
    raw_user = message.sender_chat or message.from_user
    raw_chat = message.chat
    if not raw_user or not raw_chat:
        return
    if not raw_user.id or not raw_chat.id:
        return

    chat_config = await database.get_chat_config(raw_chat)
    if not chat_config.waifu_enabled:
        await message.reply(
            text=i18n.t("bot.msg.waifu.disabled", locale=chat_config.lang)
        )
        return
    if await common.memstore.get(enums.GLockKey.CLEANING, False):
        await message.reply(text=i18n.t("bot.msg.cleanning", locale=chat_config.lang))
        return
    lock_key = utils.waifu_waiting_key(raw_user.id, raw_chat.id)
    if await common.memstore.get(lock_key):
        return
    await common.memstore.set(lock_key, True)
    waifu: UserData | None = None
    try:
        user = await database.upsert_user(raw_user)
        chat: ChatData = await database.upsert_chat(raw_chat)
        await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
        waifu, is_got = await utils.get_waifu_for_user(user, chat)
        if not waifu:
            await message.reply_text(
                text=i18n.t("bot.msg.waifu.not_found", locale=chat_config.lang)
            )
            return
        if waifu.is_married and user.id != waifu.married_waifu_id:
            await message.reply_text(
                text=i18n.t("bot.msg.waifu.retry", locale=chat_config.lang)
            )
            return
        if not is_got:
            ok = await database.set_user_waifu_in_chat(user, chat, waifu)
            if not ok:
                logger.error(
                    f"failed to set waifu {waifu.id} for user {user.id} in chat {chat.id}"
                )
                return
        waifu_markup = utils.waifu_markup(waifu.id, user.id, chat_config.lang)
        text = await utils.waifu_text(waifu, is_got, user, lang=chat_config.lang)
        if user.id == waifu.married_waifu_id:
            text = i18n.t("bot.msg.waifu.married", locale=chat_config.lang).format(
                user=await common.mention_html(user),
                waifu=await common.mention_html(waifu),
            )
            waifu_markup = None
        photo = await common.ChatAvatar(waifu.id).get_big_photo()
        if not photo:
            await message.reply_text(
                text=text,
                reply_markup=waifu_markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            return
        try:
            msg = await message.reply_photo(
                photo=(
                    BytesIO(photo)
                    if isinstance(photo, (bytes, bytearray, memoryview))
                    else photo
                ),
                caption=text,
                reply_markup=waifu_markup,  # type: ignore
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            if msg.photo is not None:
                await database.update_user_avatar(
                    waifu.id, avatar_big_id=msg.photo.file_id
                )
        except pyrogram.errors.BadRequest as e:
            logger.error(f"failed to send photo in chat {raw_chat.id}: {e})")
            await message.reply_text(
                text=text,
                reply_markup=waifu_markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
    finally:
        await common.memstore.delete(lock_key)
        if waifu:
            await common.ChatAvatar(waifu.id).save_if_not_exists(False)


@PyrogramClient.on_message(
    pyrogram.filters.command("waifu_graph") & pyrogram.filters.group, group=0
)
async def waifu_graph(client: PyrogramClient, message: pyrogram.types.Message):
    chat = message.chat
    if not chat or not chat.id:
        return
    chat_config = await database.get_chat_config(chat)
    if not chat_config.waifu_enabled:
        return
    if await common.memstore.get(enums.GLockKey.CLEANING, False):
        return
    await message.reply(text=i18n.trl("bot.msg.loading", locale=chat_config.lang))
    await utils.send_waifu_graph(chat.id, message.id, client)


@PyrogramClient.on_callback_query(pyrogram.filters.regex(r"^remove_waifu"), group=0)
async def remove_waifu(client: PyrogramClient, query: pyrogram.types.CallbackQuery):
    chat = query.message.chat
    user = query.from_user
    if not chat or not user:
        return
    if not chat.id or not user.id:
        return
    if not await common.can_user_manage_bot_in_chat(user, chat):
        user_config = await database.get_user_config(user)
        await query.answer(
            text=i18n.t("bot.msg.no_permission_group", locale=user_config.lang),
            show_alert=True,
            cache_time=10,
        )
        return
    db_chat = await database.get_chat_by_id(chat.id)
    if not db_chat:
        return
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    data = str(query.data).split(" ")
    waifu_id = int(data[1])
    user_id = int(data[2])
    db_waifu = await database.get_user_by_id(waifu_id)
    db_user: UserData = await database.get_user_by_id(user_id)
    if not db_waifu or not db_user:
        await query.answer(
            text=i18n.t("bot.msg.waifu.remove_not_found", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return

    if data[0].endswith("confirm"):
        await database.remove_user_waifu_in_chat(db_user, db_chat)
        await database.remove_association(waifu_id, chat.id)
        text = i18n.t("bot.msg.waifu.removed", locale=lang).format(
            user=html.escape(db_user.full_name),
        )
        if query.message.photo is not None:
            await query.message.edit_caption(
                caption=text,
                # reply_markup=None,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        else:
            await query.message.edit_text(
                text=text,
                # reply_markup=None,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        return

    markup = utils.remove_markup(waifu_id, user_id, lang=lang)

    if data[0].endswith("cancel"):
        markup = utils.waifu_markup(waifu_id, user_id, lang=lang)
        text = await utils.waifu_text(db_waifu, False, db_user, lang=lang)
        if query.message.photo is not None:
            await query.message.edit_caption(
                caption=text,
                reply_markup=markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        else:
            await query.message.edit_text(
                text=text, reply_markup=markup, parse_mode=pyrogram.enums.ParseMode.HTML
            )
        return

    if query.message.photo is not None:
        await query.message.edit_caption(
            caption=i18n.t("bot.msg.waifu.remove", locale=lang), reply_markup=markup
        )
    else:
        await query.message.edit_text(
            text=i18n.t("bot.msg.waifu.remove", locale=lang), reply_markup=markup
        )


@PyrogramClient.on_callback_query(pyrogram.filters.regex(r"^marry_waifu"), group=0)
async def marry_waifu(client: PyrogramClient, query: pyrogram.types.CallbackQuery):
    chat = query.message.chat
    if not chat or not chat.id:
        return
    update_user = query.from_user
    data = str(query.data).split(" ")
    waifu_id = int(data[1])
    user_id = int(data[2])
    db_waifu = await database.get_user_by_id(waifu_id)
    db_user = await database.get_user_by_id(user_id)
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    if not db_waifu.is_real_user:
        await query.answer(
            text=i18n.t("bot.msg.waifu.marry_not_real", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return

    if data[0].endswith("agree"):
        if update_user.id != db_waifu.id:
            await query.answer(
                text=i18n.t("bot.msg.waifu.marry_not_user", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        update_db_user = await database.get_user_by_id(update_user.id)
        if update_db_user.married_waifu_id is not None:
            if update_db_user.married_waifu_id == db_waifu.id:
                await query.answer(
                    text=i18n.t("bot.msg.waifu.already_married", locale=lang),
                    show_alert=True,
                    cache_time=10,
                )
            else:
                await query.answer(
                    text=i18n.t(
                        "bot.msg.waifu.user_already_married_other", locale=lang
                    ),
                    show_alert=True,
                    cache_time=10,
                )
            return
        db_waifu = await database.get_user_by_id(waifu_id)
        if db_waifu.married_waifu_id is not None:
            if db_waifu.married_waifu_id == update_user.id:
                await query.answer(
                    text=i18n.t("bot.msg.waifu.already_married", locale=lang),
                    show_alert=True,
                    cache_time=10,
                )
            else:
                await query.answer(
                    text=i18n.t(
                        "bot.msg.waifu.waifu_already_married_other", locale=lang
                    ),
                    show_alert=True,
                    cache_time=10,
                )
            return
        await database.make_wedding(db_user.id, db_waifu.id, chat.id)
        text = i18n.t("bot.msg.waifu.marry_success", locale=lang).format(
            user=await common.mention_html(db_user),
            waifu=await common.mention_html(db_waifu),
        )
        if query.message.photo is not None:
            await query.message.edit_caption(
                caption=text,
                reply_markup=None,  # type: ignore
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        else:
            await query.message.edit_text(
                text=text,
                reply_markup=None,  # type: ignore
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        return
    if data[0].endswith("refuse"):
        if update_user.id != db_waifu.id:
            await query.answer(
                text=i18n.t("bot.msg.waifu.marry_not_user", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        await query.answer(
            text=i18n.t("bot.msg.waifu.marry_refused", locale=lang), cache_time=10
        )
        text = await utils.waifu_text(db_waifu, False, db_user, lang=lang)
        if query.message.photo is not None:
            await query.message.edit_caption(
                caption=text,
                reply_markup=None,  # type: ignore
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        else:
            await query.message.edit_text(
                text=text,
                reply_markup=None,  # type: ignore
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        return
    if data[0].endswith("cancel"):
        if update_user.id not in (db_user.id, db_waifu.id):
            await query.answer(
                text=i18n.t("bot.msg.waifu.marry_not_user", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        await query.answer(
            text=i18n.t("bot.msg.waifu.marry_cancel", locale=lang), cache_time=10
        )
        text = await utils.waifu_text(db_waifu, False, db_user, lang=lang)
        if query.message.photo is not None:
            await query.message.edit_caption(caption=text, reply_markup=None)  # type: ignore
        else:
            await query.message.edit_text(text=text, reply_markup=None)  # type: ignore
        return

    if update_user.id == db_waifu.id:
        await query.answer(
            text=i18n.t("bot.msg.waifu.marry_self", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return
    if update_user.id != db_user.id:
        await query.answer(
            text=i18n.t("bot.msg.waifu.marry_not_user", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return
    if db_waifu.is_married:
        if db_waifu.married_waifu_id == update_user.id:
            await query.answer(
                text=i18n.t("bot.msg.waifu.already_married", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        else:
            await query.answer(
                text=i18n.t("bot.msg.waifu.already_married_other", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return

    text = i18n.t("bot.msg.waifu.marry_ask", locale=lang).format(
        user=await common.mention_html(update_user),
        waifu=await common.mention_html(db_waifu),
    )
    markup = utils.marry_markup(waifu_id, user_id, lang)
    if query.message.photo is not None:
        await query.message.edit_caption(
            caption=text, reply_markup=markup, parse_mode=pyrogram.enums.ParseMode.HTML
        )
    else:
        await query.message.edit_text(
            text=text, reply_markup=markup, parse_mode=pyrogram.enums.ParseMode.HTML
        )


@PyrogramClient.on_callback_query(
    pyrogram.filters.regex(r"^user_waifu_manage"), group=0
)
async def user_waifu_manage(
    client: PyrogramClient, query: pyrogram.types.CallbackQuery
):
    db_user = await database.get_user_by_id(query.from_user.id)
    if not db_user:
        return
    lang = db_user.user_config.lang
    data = str(query.data)
    if "divorce_confirm" in data:
        if not db_user.married_waifu_id or not db_user.is_married:
            return
        married_waifu = await database.get_user_by_id(db_user.married_waifu_id)
        if not married_waifu:
            await query.answer(
                text=i18n.t(
                    "bot.msg.waifu.divorce_not_found", locale=db_user.user_config.lang
                ),
                show_alert=True,
                cache_time=10,
            )
            return
        await database.divorce(db_user.id)
        await query.edit_message_text(
            text=i18n.t(
                "bot.msg.waifu.divorce_success",
                locale=db_user.user_config.lang,
            ),
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.back", locale=lang),
                            callback_data="back_home",
                        )
                    ]
                ]
            ),
            parse_mode=pyrogram.enums.ParseMode.HTML,
        )
        await client.send_message(
            chat_id=married_waifu.id,
            text=i18n.t(
                "bot.msg.waifu.divorce_notify",
                locale=married_waifu.user_config.lang,
            ).format(
                user=html.escape(db_user.full_name),
            ),
            parse_mode=pyrogram.enums.ParseMode.HTML,
        )
        return
    if "divorce" in data:
        if not db_user.married_waifu_id or not db_user.is_married:
            await query.answer(
                text=i18n.t("bot.msg.waifu.divorce_not_married", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        married_waifu = await database.get_user_by_id(db_user.married_waifu_id)
        if not married_waifu:
            await query.answer(
                text=i18n.t("bot.msg.waifu.divorce_not_found", locale=lang),
                show_alert=True,
                cache_time=10,
            )
            return
        await query.edit_message_text(
            text=i18n.t(
                "bot.msg.waifu.divorce_confirm",
                locale=lang,
            ).format(
                waifu=html.escape(married_waifu.full_name),
            ),
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t(
                                "bot.button.waifu.divorce_confirm",
                                locale=lang,
                            ),
                            callback_data="user_waifu_manage divorce_confirm",
                        ),
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t(
                                "bot.button.waifu.divorce_cancel",
                                locale=lang,
                            ),
                            callback_data="back_home",
                        ),
                    ]
                ]
            ),
        )
        return
    if "set_waifu_mention" in data:
        db_user.waifu_mention = not db_user.waifu_mention
        await database.update_user(
            db_user.id, db_user.waifu_mention, db_user.is_bot_global_admin
        )
    set_mention_text = (
        i18n.t(
            "bot.button.waifu.mention_enabled",
            locale=lang,
        )
        if db_user.waifu_mention
        else i18n.t(
            "bot.button.waifu.mention_disabled",
            locale=lang,
        )
    )
    await query.edit_message_text(
        i18n.t("bot.msg.waifu.info", locale=lang).format(
            mention=db_user.waifu_mention,
            married=db_user.is_married,
            married_waifu_id=db_user.married_waifu_id,
        ),
        reply_markup=pyrogram.types.InlineKeyboardMarkup(
            [
                [
                    pyrogram.types.InlineKeyboardButton(
                        text=set_mention_text,
                        callback_data="user_waifu_manage set_waifu_mention",
                    ),
                    pyrogram.types.InlineKeyboardButton(
                        text=i18n.t("bot.button.waifu.divorce", locale=lang),
                        callback_data="user_waifu_manage divorce",
                    ),
                ],
                [
                    pyrogram.types.InlineKeyboardButton(
                        text=i18n.t("bot.button.back", locale=lang),
                        callback_data="back_home",
                    ),
                ],
            ]
        ),
    )
