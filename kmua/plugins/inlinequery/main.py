import pyrogram

from kmua import database, i18n

from . import hack
from .quote import query_quote


@pyrogram.Client.on_inline_query()
async def inline_query_handler(
    client: pyrogram.Client, query: pyrogram.types.InlineQuery
):
    user = query.from_user
    user_config = await database.get_user_config(user)
    datas = query.query.strip().split(" ")
    if not datas or datas[0] == "":
        results = []
        if query.chat_type == pyrogram.enums.ChatType.SUPERGROUP:
            results.append(
                pyrogram.types.InlineQueryResultArticle(
                    id="chat_quotes",
                    title=i18n.t(
                        "bot.inline.chat_quotes_title", locale=user_config.lang
                    ),
                    description=i18n.t(
                        "bot.inline.chat_quotes_description", locale=user_config.lang
                    ),
                    input_message_content=pyrogram.types.InputTextMessageContent(
                        message_text=i18n.t(
                            "bot.inline.chat_quotes_quering", locale=user_config.lang
                        ),
                    ),
                    reply_markup=pyrogram.types.InlineKeyboardMarkup(
                        [
                            [
                                pyrogram.types.InlineKeyboardButton(
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
                pyrogram.types.InlineQueryResultArticle(
                    id="quotes",
                    title=i18n.t("bot.inline.quotes_title", locale=user_config.lang),
                    description=i18n.t(
                        "bot.inline.quotes_description", locale=user_config.lang
                    ),
                    input_message_content=pyrogram.types.InputTextMessageContent(
                        message_text=i18n.t(
                            "bot.inline.quotes_message", locale=user_config.lang
                        ),
                    ),
                    reply_markup=pyrogram.types.InlineKeyboardMarkup(
                        [
                            [
                                pyrogram.types.InlineKeyboardButton(
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
            return await query_quote(client, query, chat_id, text)
        return await query_quote(client, query, text=text)


@pyrogram.Client.on_chosen_inline_result()
async def chosen_inline_result(
    client: pyrogram.Client, result: pyrogram.types.ChosenInlineResult
):
    user = result.from_user
    user_config = await database.get_user_config(user)
    info = None
    try:
        info = hack.resolve_inline_message_id(result.inline_message_id)
    except Exception as e:
        pass
    if result.result_id == "chat_quotes":
        if info is None:
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text=i18n.t("bot.inline.chat_quotes_error", locale=user_config.lang),
            )
            return
        await client.edit_inline_text(
            inline_message_id=result.inline_message_id,
            text=i18n.t("bot.inline.chat_quotes_success", locale=user_config.lang),
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            switch_inline_query_current_chat=f"q_{info.chat_id} ",
                            text=i18n.t(
                                "bot.inline.chat_quotes_button", locale=user_config.lang
                            ),
                        )
                    ]
                ]
            ),
        )
        return
