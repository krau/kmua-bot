import asyncio
from io import BytesIO

from PIL import Image
from pyrogram import enums, types
from pyrogram.client import Client

from kmua import database, i18n
from kmua.common.memory_store import memttlcache
from kmua.logger import logger
from kmua.plugins.inlinequery.manomeme import handle_manomeme

from . import hack, manodrawer
from .quote import query_quote


@Client.on_inline_query()
async def inline_query_handler(client: Client, query: types.InlineQuery):
    user = query.from_user
    user_config = await database.get_user_config(user)
    datas = query.query.strip().split(" ")
    if not datas or datas[0] == "":
        results: list[types.InlineQueryResult] = []
        if query.chat_type == enums.ChatType.SUPERGROUP:
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
        results.append(
            types.InlineQueryResultArticle(
                title="魔裁 MEME",
                description="魔法少女的魔女审判相关 MEME 生成",
                input_message_content=types.InputTextMessageContent(
                    message_text="""
魔裁 MEME 生成器, 用法:

1. 安安说: ms anan [表情] [文本]
示例: ms anan 无语 吾辈现在不想说话
2. 辩论: ms trial [角色] ([类型] 文本...)
示例: ms trial 希罗 [伪证] 我当时睡得可香了
"""
                ),
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                text="安安说",
                                switch_inline_query_current_chat="ms anan ",
                            ),
                            types.InlineKeyboardButton(
                                text="辩论",
                                switch_inline_query_current_chat="ms trial ",
                            ),
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
        # quotes
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
    elif datas[0].startswith("ms"):
        # manosaba memes
        datas = datas[1:]
        await handle_manomeme(client, query, datas)


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
    if result.result_id == "chat_quotes":
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
    elif result.result_id == "pick_bottle":
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

        row1 = [
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.throw_back", locale=lang),
                callback_data=f"throw_back {user.id}",
            )
        ]
        if bottle.sender_id == user.id:
            row1.append(
                types.InlineKeyboardButton(
                    i18n.t("bot.button.bottle.destroy", locale=lang),
                    callback_data=f"destroy_bottle {bottle.id} {user.id}",
                ),
            )
        buttons = [
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
    elif result.result_id.startswith("ms_"):
        dataid = result.result_id.split("_")[1]
        data: dict | None = await memttlcache.get(f"manomeme_inline:{dataid}")
        if data is None:
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text="查询过期了呢, 请重新生成",
            )
            return
        match data["type"]:
            case "anan":
                face = data.get("face", "无语")
                text = data.get("text", "吾辈现在不想说话")
                try:
                    image_bytes = await asyncio.to_thread(
                        manodrawer.draw_anan, text, face
                    )
                    media = BytesIO(image_bytes)
                    media.name = "anan.png"
                    await client.edit_inline_media(
                        inline_message_id=result.inline_message_id,
                        media=types.InputMediaPhoto(media=media),
                        reply_markup=types.InlineKeyboardMarkup(
                            [
                                [
                                    types.InlineKeyboardButton(
                                        text="安安说",
                                        switch_inline_query_current_chat=f"ms anan {face} ",
                                    )
                                ]
                            ]
                        ),
                    )
                except Exception as e:
                    logger.exception(f"Failed to edit inline media: {e}")
                    await client.edit_inline_text(
                        inline_message_id=result.inline_message_id,
                        text="生成图片失败了呢, 请稍后再试",
                    )
                return
            case "trial":
                character = data.get("character", manodrawer.Character.EMA)
                options = data.get("options", [])
                if not options:
                    await client.edit_inline_text(
                        inline_message_id=result.inline_message_id,
                        text="没有有效的选项呢, 请重新生成",
                    )
                    return
                try:
                    image_bytes = await asyncio.to_thread(
                        manodrawer.draw_trial, character, options
                    )
                    media = BytesIO(image_bytes)
                    media.name = "trial.png"
                    is_hiro = character == manodrawer.Character.HIRO
                    await client.edit_inline_media(
                        inline_message_id=result.inline_message_id,
                        media=types.InputMediaPhoto(media=media),
                    )
                except Exception as e:
                    logger.exception(f"Failed to edit inline media: {e}")
                    await client.edit_inline_text(
                        inline_message_id=result.inline_message_id,
                        text="生成图片失败了呢, 请稍后再试",
                    )
                return
