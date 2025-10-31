import random

from pyrogram import enums, filters, types
from pyrogram.client import Client

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger


@Client.on_message(filters.command(["bottle", "throwbottle"]), group=0)
async def throw_bottle(client: Client, message: types.Message):
    # 在命令后直接跟文本内容作为瓶中信
    # 或者用命令回复一条消息, 将该消息内容作为瓶中信
    lang = "zh-CN"
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        config = await database.get_user_config(message.from_user.id)
        lang = config.lang
    else:
        config = await database.get_chat_config(message.chat.id)
        lang = config.lang

    bottle_message = message.reply_to_message or message
    sender = message.sender_chat or message.from_user
    if not sender or not sender.id:
        return
    file_id = None
    media_type = None
    if bottle_message.media:
        match bottle_message.media:
            case enums.MessageMediaType.PHOTO:
                file_id = bottle_message.photo.file_id if bottle_message.photo else None
                media_type = enums.MessageMediaType.PHOTO.name
            case enums.MessageMediaType.VIDEO:
                file_id = bottle_message.video.file_id if bottle_message.video else None
                media_type = enums.MessageMediaType.VIDEO.name
            case enums.MessageMediaType.AUDIO:
                file_id = bottle_message.audio.file_id if bottle_message.audio else None
                media_type = enums.MessageMediaType.AUDIO.name
            case enums.MessageMediaType.DOCUMENT:
                file_id = (
                    bottle_message.document.file_id if bottle_message.document else None
                )
                media_type = enums.MessageMediaType.DOCUMENT.name
            case enums.MessageMediaType.ANIMATION:
                file_id = (
                    bottle_message.animation.file_id
                    if bottle_message.animation
                    else None
                )
                media_type = enums.MessageMediaType.ANIMATION.name
            case _:
                await message.reply_text(
                    i18n.t("bot.msg.bottle.unsupported_media_throw", locale=lang)
                )
                return
    # 异或非
    if (file_id is None) != (media_type is None):
        file_id = None
        media_type = None
    text = None
    if bottle_message.command:
        if len(bottle_message.command) > 1:
            text = " ".join(bottle_message.command[1:])
        else:
            text = ""
    elif bottle_message.caption or bottle_message.text:
        text = bottle_message.caption or bottle_message.text
    if not text and not file_id:
        await message.reply_text(i18n.t("bot.msg.bottle.no_content", locale=lang))
        return
    if text is not None and len(text) >= 4096:
        await message.reply_text(i18n.t("bot.msg.bottle.text_too_long", locale=lang))
        return
    db_user = await database.get_user_by_id(sender.id)
    if db_user is None:
        return
    count: int = 0
    try:
        count = (
            await common.memttlcache.get(f"user:{sender.id}:throw_bottle_count") or 0
        )
        coins = db_user.user_config.coins
        if coins < app_config.cost_throw_bottle_base:
            await message.reply_text(
                i18n.t("bot.msg.bottle.not_enough_coins", locale=lang)
            )
            return
        cost = app_config.cost_throw_bottle_base * (
            count**app_config.cost_throw_bottle_pow
        )
        await database.add_bottle(
            sender_id=sender.id,
            text=text,
            file_id=file_id,
            media_type=media_type,
            cost=cost,
        )
    except Exception as e:
        await message.reply_text(i18n.t("bot.msg.bottle.throw_failed", locale=lang))
        logger.exception(f"Failed to add bottle: {e}")
        return
    await message.reply_text(i18n.t("bot.msg.bottle.throw_success", locale=lang))
    await common.memttlcache.set(
        f"user:{sender.id}:throw_bottle_count", count + 1, ttl=3600
    )


@Client.on_message(filters.command("pickbottle"), group=0)
async def pick_bottle(client: Client, message: types.Message):
    lang = "zh-CN"
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        config = await database.get_user_config(message.from_user.id)
        lang = config.lang
    else:
        config = await database.get_chat_config(message.chat.id)
        lang = config.lang
        if not config.pick_bottle_enabled:
            await message.reply_text(
                i18n.t("bot.msg.bottle.pick_disabled_in_chat", locale=lang)
            )
            return

    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return
    bot_username = client.me.username if client.me else None
    if bot_username is None:
        return
    db_user = await database.get_user_by_id(user.id)
    if db_user is None:
        return
    if db_user.user_config.coins < -144 * 16:
        await message.reply_text(
            i18n.t("bot.msg.bottle.not_enough_coins_to_pick", locale=lang)
        )
    try:
        count = await common.memttlcache.get(f"user:{user.id}:pick_bottle_count") or 0
        cost = app_config.cost_pick_bottle_base * (
            count**app_config.cost_pick_bottle_pow
        )
        bottle = await database.pick_random_bottle()
        if bottle is None:
            await message.reply_text(i18n.t("bot.msg.bottle.no_bottles", locale=lang))
            return
        await common.memttlcache.set(
            f"user:{user.id}:pick_bottle_count", count + 1, ttl=60
        )
        await database.cost_user_coins(user.id, cost)
    except Exception as e:
        await message.reply_text(i18n.t("bot.msg.bottle.pick_failed", locale=lang))
        logger.exception(f"Failed to pick bottle: {e}")
        return

    buttons = [
        [
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.throw_back", locale=lang),
                callback_data=f"throw_back {user.id}",
            ),
            # types.InlineKeyboardButton(
            #     i18n.t("bot.button.bottle.destroy", locale=lang),
            #     callback_data=f"destroy_bottle {bottle.id} {user.id}",
            # ),
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
    reply_markup = types.InlineKeyboardMarkup(buttons)

    content_kwargs = {}
    if bottle.text:
        content_kwargs["caption"] = bottle.text
    if bottle.media_type and bottle.file_id:
        match bottle.media_type:
            case enums.MessageMediaType.PHOTO.name:
                await message.reply_photo(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.VIDEO.name:
                await message.reply_video(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.AUDIO.name:
                await message.reply_audio(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.DOCUMENT.name:
                await message.reply_document(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.ANIMATION.name:
                await message.reply_animation(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case _:
                await message.reply_text(
                    i18n.t("bot.msg.bottle.unsupported_media", locale=lang)
                )
    elif bottle.text:
        await message.reply_text(
            bottle.text,
            reply_markup=reply_markup,
        )


@Client.on_callback_query(filters.regex(r"^throw_back"), group=0)
async def handle_throw_back_callback(
    client: Client, callback_query: types.CallbackQuery
):
    user = callback_query.from_user
    if not user or not user.id:
        return
    lang = (await database.get_user_config(user.id)).lang
    data = str(callback_query.data).split(" ")
    if len(data) != 2:
        return
    user_id = int(data[1])
    if callback_query.from_user.id != user_id:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.not_your_bottle", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return
    if callback_query.message is None:
        if callback_query.inline_message_id is not None:
            await callback_query.edit_message_text(
                i18n.t("bot.msg.bottle.throw_back_success", locale=lang)
            )
            return
        await callback_query.answer(
            i18n.t("bot.msg.bottle.throw_back_success", locale=lang)
        )
        return
    if callback_query.message.media:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.throw_back_success", locale=lang)
        )
        await callback_query.message.delete()
        return
    await callback_query.edit_message_text(
        i18n.t("bot.msg.bottle.throw_back_success", locale=lang)
    )


# 举报
@Client.on_callback_query(filters.regex(r"^report_bottle"), group=0)
async def handle_report_bottle_callback(
    client: Client, callback_query: types.CallbackQuery
):
    user = callback_query.from_user
    if not user or not user.id:
        return
    lang = (await database.get_user_config(user.id)).lang
    data = str(callback_query.data).split(" ")
    if len(data) != 2:
        return
    bottle_id = int(data[1])
    try:
        await database.report_bottle(bottle_id)
    except Exception as e:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.report_failed", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        logger.exception(f"Failed to report bottle: {e}")
        return
    if callback_query.message is None:
        return
    await callback_query.answer(
        i18n.t("bot.msg.bottle.report_success", locale=lang), cache_time=3000
    )


# 销毁
@Client.on_callback_query(filters.regex(r"^destroy_bottle"), group=0)
async def handle_destroy_bottle_callback(
    client: Client, callback_query: types.CallbackQuery
):
    user = callback_query.from_user
    if not user or not user.id:
        return
    lang = (await database.get_user_config(user.id)).lang
    data = str(callback_query.data).split(" ")
    if len(data) != 3:
        return
    bottle_id = int(data[1])
    user_id = int(data[2])
    if callback_query.from_user.id != user_id:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.not_your_bottle", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return
    try:
        await database.delete_bottle(bottle_id)
    except Exception as e:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.destroy_failed", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        logger.exception(f"Failed to delete bottle: {e}")
        return
    if callback_query.message is None:
        await callback_query.edit_message_text(
            i18n.t("bot.msg.bottle.destroy_success", locale=lang)
        )
        return
    await callback_query.answer(i18n.t("bot.msg.bottle.destroy_success", locale=lang))
    await callback_query.message.delete()
