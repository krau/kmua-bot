import pyrogram

from kmua import database


async def query_quote(
    client: pyrogram.Client,
    query: pyrogram.types.InlineQuery,
    chat_id: int | None = None,
    text: str = "",
):
    user = query.from_user
    results = []
    if chat_id is not None:
        if not await database.get_association(user.id, chat_id):
            return
        quotes = await database.take_chat_quotes(
            chat_id=chat_id,
            query=text,
            limit=50,
        )
    else:
        quotes = await database.take_quotes_user_can_see(user.id, text, 50)
    for quote in quotes:
        # button_text = (
        #     quote_db.user.full_name
        #     if len(quote_db.user.full_name) <= 16
        #     else quote_db.user.full_name[:16] + "..."
        #     if quote_db.user.full_name
        #     else str(quote_db.user_id)
        # )
        # markup = pyrogram.types.InlineKeyboardMarkup(
        #     [
        #         [
        #             pyrogram.types.InlineKeyboardButton(
        #                 text=button_text,
        #                 url=quote_db.link,
        #             )
        #         ]
        #     ]
        # )

        # https://github.com/krau/kmua-bot/issues/71
        markup = pyrogram.types.InlineKeyboardMarkup(
            [[pyrogram.types.InlineKeyboardButton(text="↗️", url=quote.link)]]
        )
        if quote.img:
            results.append(
                pyrogram.types.InlineQueryResultCachedPhoto(
                    quote.img,
                    title=quote.text or "",
                    reply_markup=markup,
                )
            )
        results.append(
            pyrogram.types.InlineQueryResultArticle(
                title=quote.text or "",
                input_message_content=pyrogram.types.InputTextMessageContent(
                    message_text=quote.text,
                ),
                description=quote.user.full_name,
                reply_markup=markup,
            )
        )
        if len(results) >= 50:
            break
    await query.answer(results[:49], cache_time=5, is_personal=True)
