from pyrogram import enums, types
from pyrogram.client import Client

from kmua import database, i18n
from kmua.logger import logger

from . import hack
from .quote import query_quote


@Client.on_inline_query()
async def inline_query_handler(client: Client, query: types.InlineQuery):
    user = query.from_user
    user_config = await database.get_user_config(user)
    datas = query.query.strip().split(" ")
    if not datas or datas[0] == "":
        results = []
        if query.chat_type == pyrogram.enums.ChatType.SUPERGROUP:
            results.append(
                types.InlineQueryResultArticle(
                    id="chat_quotes",
                    title=i18n.t(
                        "bot.inline.chat_quotes_title", locale=user_config.lang
                    ),
                    description=i18n.t(
                        "bot.inline.chat_quotes_description", locale=user_config.lang
                    ),
                    input_message_content=types.InputTextMessageContent(
                        message_text=i18n.t(
                            "bot.inline.chat_quotes_quering", locale=user_config.lang
                        ),
                    ),
                    reply_markup=types.InlineKeyboardMarkup(
                        [
                            [
                                types.InlineKeyboardButton(
                                    text=i18n.t(
                                        "bot.inline.chat_quotes_button_noop",
                                        locale=user_config.lang,
                                    ),
                                    callback_data="noop",
                                )
                            ]
                        ]
                    ),
                )
            )
        else:
            results.append(
                types.InlineQueryResultArticle(
                    id="quotes",
                    title=i18n.t("bot.inline.quotes_title", locale=user_config.lang),
                    description=i18n.t(
                        "bot.inline.quotes_description", locale=user_config.lang
                    ),
                    input_message_content=types.InputTextMessageContent(
                        message_text=i18n.t(
                            "bot.inline.quotes_message", locale=user_config.lang
                        ),
                    ),
                    reply_markup=types.InlineKeyboardMarkup(
                        [
                            [
                                types.InlineKeyboardButton(
                                    text=i18n.t(
                                        "bot.inline.quotes_button",
                                        locale=user_config.lang,
                                    ),
                                    switch_inline_query_current_chat="q ",
                                )
                            ]
                        ]
                    ),
                )
            )
        results.append(
            types.InlineQueryResultArticle(
                id="pick_bottle",
                title=i18n.t("bot.inline.pick_bottle_title", locale=user_config.lang),
                description=i18n.t(
                    "bot.inline.pick_bottle_description", locale=user_config.lang
                ),
                input_message_content=types.InputTextMessageContent(
                    message_text=i18n.t(
                        "bot.inline.pick_bottle_quering", locale=user_config.lang
                    ),
                ),
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                text=i18n.t(
                                    "bot.inline.resolve_button_noop",
                                    locale=user_config.lang,
                                ),
                                callback_data="noop",
                            )
                        ]
                    ]
                ),
            )
        )
        await query.answer(
            results=results,
            switch_pm_text=i18n.t("bot.inline.switch_pm_text"),
            switch_pm_parameter="inline_query",
        )
        return
    if datas[0].startswith("q"):
        q_data = datas[0].split("_")
        text = " ".join(datas[1:])
        if len(q_data) > 1:
            try:
                chat_id = int(q_data[1])
            except ValueError:
                chat_id = None
            await query_quote(client, query, chat_id, text)
            return
        await query_quote(client, query, text=text)


@Client.on_chosen_inline_result()
async def chosen_inline_result(client: Client, result: types.ChosenInlineResult):
    user = result.from_user
    user_config = await database.get_user_config(user)
    info = None
    try:
        info = hack.resolve_inline_message_id(result.inline_message_id)
    except Exception as e:
        logger.warning(f"Failed to resolve inline message id: {e}")
    if info is None:
        await client.edit_inline_text(
            inline_message_id=result.inline_message_id,
            text=i18n.t("bot.inline.resolve_error", locale=user_config.lang),
        )
        return
    match result.result_id:
        case "chat_quotes":
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text=i18n.t("bot.inline.chat_quotes_success", locale=user_config.lang),
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                switch_inline_query_current_chat=f"q_{info.chat_id} ",
                                text=i18n.t(
                                    "bot.inline.chat_quotes_button",
                                    locale=user_config.lang,
                                ),
                            )
                        ]
                    ]
                ),
            )
            return
        case "pick_bottle":
            lang = user_config.lang
            chat = await database.get_chat_by_id(info.chat_id)
            if chat is not None:
                lang = chat.chat_config.lang
                if not chat.chat_config.pick_bottle_enabled:
                    await client.edit_inline_text(
                        inline_message_id=result.inline_message_id,
                        text=i18n.t(
                            "bot.msg.bottle.pick_disabled_in_chat",
                            locale=lang,
                        ),
                    )
                    return
            bottle = await database.pick_random_bottle()
            if bottle is None:
                await client.edit_inline_text(
                    inline_message_id=result.inline_message_id,
                    text=i18n.t("bot.msg.bottle.no_bottles", locale=user_config.lang),
                )
                return
            bot_username = client.me.username if client.me else None
            buttons = [
                [
                    types.InlineKeyboardButton(
                        i18n.t("bot.button.bottle.throw_back", locale=lang),
                        callback_data=f"throw_back {user.id}",
                    ),
                    types.InlineKeyboardButton(
                        i18n.t("bot.button.bottle.destroy", locale=lang),
                        callback_data=f"destroy_bottle {bottle.id} {user.id}",
                    ),
                ],
                [
                    types.InlineKeyboardButton(
                        i18n.t("bot.button.bottle.report", locale=lang),
                        callback_data=f"report_bottle {bottle.id}",
                    ),
                    types.InlineKeyboardButton(
                        i18n.t("bot.button.bottle.seek", locale=lang),
                        url=f"https://t.me/{bot_username}?start=seek_bottle_{bottle.id}",
                    ),
                ],
            ]
            if bottle.media_type is not None and bottle.file_id is not None:
                try:
                    media = None
                    match bottle.media_type:
                        case enums.MessageMediaType.PHOTO.name:
                            media = types.InputMediaPhoto(
                                media=bottle.file_id, caption=bottle.text
                            )
                        case enums.MessageMediaType.VIDEO.name:
                            media = types.InputMediaVideo(
                                media=bottle.file_id, caption=bottle.text
                            )
                        case enums.MessageMediaType.AUDIO.name:
                            media = types.InputMediaAudio(
                                media=bottle.file_id, caption=bottle.text
                            )
                        case enums.MessageMediaType.DOCUMENT.name:
                            media = types.InputMediaDocument(
                                media=bottle.file_id, caption=bottle.text
                            )
                        case enums.MessageMediaType.ANIMATION.name:
                            media = types.InputMediaAnimation(
                                media=bottle.file_id, caption=bottle.text
                            )
                    if media is not None:
                        await client.edit_inline_media(
                            inline_message_id=result.inline_message_id,
                            media=media,
                            reply_markup=types.InlineKeyboardMarkup(buttons),
                        )
                        return
                except Exception as e:
                    logger.exception(f"Failed to edit inline media: {e}")
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text=bottle.text,
                reply_markup=types.InlineKeyboardMarkup(buttons),
            )
            return
