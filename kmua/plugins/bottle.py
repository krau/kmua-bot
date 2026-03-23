from pyrogram import enums, filters, types
from pyrogram.client import Client

from kmua import common, database, i18n
from kmua.common.memory_store import memttlcache
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.logger import logger

_BOTTLE_MSG_PREFIX = "bottle_msg:"
_REPLY_INTENT_PREFIX = "bottle_reply_intent:"
_REPLY_COOLDOWN_PREFIX = "bottle_reply_cooldown:"
_BOTTLE_BAN_PREFIX = "bottle_ban:"


async def _bottle_reply_filter(_, client: Client, message: types.Message) -> bool:
    if not message.from_user or not message.from_user.id:
        return False
    if not is_explicit_reply(message):
        return False
    reply_to = message.reply_to_message
    if not reply_to or not reply_to.from_user or reply_to.from_user.id != client.me.id:
        return False
    if not reply_to.chat:
        return False
    bottle_data = await memttlcache.get(
        f"{_BOTTLE_MSG_PREFIX}{reply_to.chat.id}:{reply_to.id}"
    )
    if not bottle_data:
        return False
    user_id = message.from_user.id
    intent_data = await memttlcache.get(f"{_REPLY_INTENT_PREFIX}{user_id}")
    if not intent_data:
        return False
    if intent_data.get("bottle_id") != bottle_data.get("bottle_id"):
        return False
    return True


bottle_reply_filter = filters.create(_bottle_reply_filter)


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

    reply_target = common.get_reply_target(message)
    bottle_message = reply_target or message
    sender = message.sender_chat or message.from_user
    if not sender or not sender.id:
        return
    if await memttlcache.get(f"{_BOTTLE_BAN_PREFIX}{sender.id}"):
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
        f"user:{sender.id}:throw_bottle_count", count + 1, ttl=600
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
    if await memttlcache.get(f"{_BOTTLE_BAN_PREFIX}{user.id}"):
        await message.reply_text(i18n.t("bot.msg.bottle.banned", locale=lang))
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

    row1 = [
        types.InlineKeyboardButton(
            i18n.t("bot.button.bottle.throw_back", locale=lang),
            callback_data=f"throw_back {user.id}",
        ),
    ]
    if db_user.id == bottle.sender_id:
        row1.append(
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.destroy", locale=lang),
                callback_data=f"destroy_bottle {bottle.id} {user.id}",
            )
        )
    else:
        row1.append(
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.reply", locale=lang),
                callback_data=f"reply_bottle_menu {bottle.id} {user.id}",
            )
        )
    buttons = [
        row1,
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
    content_kwargs["has_spoiler"] = True
    if bottle.text:
        content_kwargs["caption"] = bottle.text
    if bottle.media_type and bottle.file_id:
        match bottle.media_type:
            case enums.MessageMediaType.PHOTO.name:
                bot_msg = await message.reply_photo(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.VIDEO.name:
                bot_msg = await message.reply_video(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.AUDIO.name:
                bot_msg = await message.reply_audio(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.DOCUMENT.name:
                bot_msg = await message.reply_document(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case enums.MessageMediaType.ANIMATION.name:
                bot_msg = await message.reply_animation(
                    bottle.file_id, reply_markup=reply_markup, **content_kwargs
                )
            case _:
                bot_msg = None
                await message.reply_text(
                    i18n.t("bot.msg.bottle.unsupported_media", locale=lang)
                )
    elif bottle.text:
        bot_msg = await message.reply_text(
            bottle.text,
            reply_markup=reply_markup,
        )
    else:
        bot_msg = None

    if bot_msg:
        original_data = {
            "bottle_id": bottle.id,
            "text": bottle.text,
            "file_id": bottle.file_id,
            "media_type": bottle.media_type,
            "user_id": user.id,
            "is_owner": db_user.id == bottle.sender_id,
            "lang": lang,
        }
        await memttlcache.set(
            f"{_BOTTLE_MSG_PREFIX}{bot_msg.chat.id}:{bot_msg.id}",
            original_data,
            ttl=86400,
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


@Client.on_callback_query(filters.regex(r"^reply_bottle_menu"), group=0)
async def handle_reply_bottle_menu_callback(
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
    bottle = await database.get_bottle_by_id(bottle_id)
    if bottle is None:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.reply_bottle_not_found", locale=lang),
            show_alert=True,
        )
        return
    if bottle.sender_id == user_id:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.not_your_bottle", locale=lang),
            show_alert=True,
        )
        return
    buttons = [
        [
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.reply_anonymous", locale=lang),
                callback_data=f"reply_bottle_start {bottle_id} {user_id} 1",
            ),
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.reply_public", locale=lang),
                callback_data=f"reply_bottle_start {bottle_id} {user_id} 0",
            ),
        ],
    ]
    await callback_query.edit_message_text(
        i18n.t("bot.msg.bottle.reply_prompt", locale=lang),
        reply_markup=types.InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^reply_bottle_start"), group=0)
async def handle_reply_bottle_start_callback(
    client: Client, callback_query: types.CallbackQuery
):
    user = callback_query.from_user
    if not user or not user.id:
        return
    lang = (await database.get_user_config(user.id)).lang
    data = str(callback_query.data).split(" ")
    if len(data) != 4:
        return
    bottle_id = int(data[1])
    user_id = int(data[2])
    is_anonymous = data[3] == "1"
    if callback_query.from_user.id != user_id:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.not_your_bottle", locale=lang),
            show_alert=True,
            cache_time=10,
        )
        return
    cooldown_key = f"{_REPLY_COOLDOWN_PREFIX}{user_id}"
    if await memttlcache.get(cooldown_key):
        await callback_query.answer(
            i18n.t("bot.msg.bottle.reply_too_fast", locale=lang),
            show_alert=True,
        )
        return
    bottle = await database.get_bottle_by_id(bottle_id)
    if bottle is None:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.reply_bottle_not_found", locale=lang),
            show_alert=True,
        )
        return
    await memttlcache.set(
        f"{_REPLY_INTENT_PREFIX}{user_id}",
        {"bottle_id": bottle_id, "is_anonymous": is_anonymous},
        ttl=300,
    )
    cancel_button = [
        [
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.cancel_reply", locale=lang),
                callback_data=f"reply_bottle_cancel {user_id}",
            ),
        ]
    ]
    await callback_query.edit_message_text(
        i18n.t("bot.msg.bottle.reply_waiting", locale=lang),
        reply_markup=types.InlineKeyboardMarkup(cancel_button),
    )


@Client.on_callback_query(filters.regex(r"^reply_bottle_cancel"), group=0)
async def handle_reply_bottle_cancel_callback(
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
    await memttlcache.delete(f"{_REPLY_INTENT_PREFIX}{user_id}")
    if callback_query.message:
        await callback_query.edit_message_text(
            i18n.t("bot.msg.bottle.reply_cancelled", locale=lang)
        )
    else:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.reply_cancelled", locale=lang)
        )


@Client.on_message(bottle_reply_filter, group=0)
async def handle_bottle_reply_message(client: Client, message: types.Message):
    user_id = message.from_user.id
    reply_to = message.reply_to_message
    bottle_data = await memttlcache.get(
        f"{_BOTTLE_MSG_PREFIX}{reply_to.chat.id}:{reply_to.id}"
    )
    intent_data = await memttlcache.get(f"{_REPLY_INTENT_PREFIX}{user_id}")

    await memttlcache.delete(f"{_REPLY_INTENT_PREFIX}{user_id}")
    is_anonymous = intent_data.get("is_anonymous", False)
    lang = (await database.get_user_config(user_id)).lang
    bottle_id = bottle_data.get("bottle_id")

    text = message.text or message.caption or ""
    file_id = None
    media_type = None
    if message.photo:
        file_id = message.photo.file_id
        media_type = enums.MessageMediaType.PHOTO.name
    elif message.video:
        file_id = message.video.file_id
        media_type = enums.MessageMediaType.VIDEO.name
    elif message.audio:
        file_id = message.audio.file_id
        media_type = enums.MessageMediaType.AUDIO.name
    elif message.document:
        file_id = message.document.file_id
        media_type = enums.MessageMediaType.DOCUMENT.name
    elif message.animation:
        file_id = message.animation.file_id
        media_type = enums.MessageMediaType.ANIMATION.name

    if not text.strip() and not file_id:
        await message.reply_text(i18n.t("bot.msg.bottle.no_reply_content", locale=lang))
        return
    if len(text) >= 4096:
        await message.reply_text(
            i18n.t("bot.msg.bottle.reply_text_too_long", locale=lang)
        )
        return
    bottle = await database.get_bottle_by_id(bottle_id)
    if bottle is None:
        await message.reply_text(
            i18n.t("bot.msg.bottle.reply_bottle_not_found", locale=lang)
        )
        return
    sender_id = bottle.sender_id
    if sender_id is None:
        await message.reply_text(
            i18n.t("bot.msg.bottle.reply_sender_not_found", locale=lang)
        )
        return
    try:
        await database.add_bottle_reply(
            bottle_id=bottle_id,
            replier_id=user_id,
            text=text,
            is_anonymous=is_anonymous,
            file_id=file_id,
            media_type=media_type,
        )
    except Exception as e:
        logger.exception(f"Failed to add bottle reply: {e}")
        await message.reply_text(i18n.t("bot.msg.bottle.reply_failed", locale=lang))
        return
    await memttlcache.set(f"{_REPLY_COOLDOWN_PREFIX}{user_id}", True, ttl=3)
    sender = await database.get_user_by_id(sender_id)
    if sender is None:
        await message.reply_text(
            i18n.t("bot.msg.bottle.reply_sender_not_found", locale=lang)
        )
        return
    sender_lang = sender.user_config.lang
    bot_username = client.me.username if client.me else None

    bottle_preview = (
        bottle.text[:100]
        if bottle.text
        else i18n.t("bot.msg.bottle.bottle_preview_media", locale=sender_lang)
    )
    if bottle.text and len(bottle.text) > 100:
        bottle_preview += "..."
    bottle_preview_text = i18n.t(
        "bot.msg.bottle.reply_bottle_preview",
        locale=sender_lang,
    ).format(preview=bottle_preview)

    if is_anonymous:
        reply_header = i18n.t(
            "bot.msg.bottle.reply_received_anonymous_header",
            locale=sender_lang,
        )
    else:
        replier = await database.get_user_by_id(user_id)
        replier_name = (
            replier.full_name if replier else message.from_user.first_name or "神秘人"
        )
        if replier and replier.username:
            replier_display = (
                f'<a href="https://t.me/{replier.username}">{replier_name}</a>'
            )
        else:
            replier_display = replier_name
        reply_header = i18n.t(
            "bot.msg.bottle.reply_received_header",
            locale=sender_lang,
        ).format(sender=replier_display)

    reply_content = f"{reply_header}\n\n{bottle_preview_text}"
    if text:
        reply_content += f"\n\n{text}"

    buttons = [
        [
            types.InlineKeyboardButton(
                i18n.t(
                    "bot.button.bottle.destroy_bottle_after_reply", locale=sender_lang
                ),
                callback_data=f"reply_destroy_bottle {bottle_id} {sender_id}",
            ),
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.keep_bottle_after_reply", locale=sender_lang),
                callback_data=f"reply_keep_bottle {sender_id}",
            ),
        ]
    ]
    if bot_username:
        buttons.append(
            [
                types.InlineKeyboardButton(
                    i18n.t("bot.button.bottle.seek", locale=sender_lang),
                    url=f"https://t.me/{bot_username}?start=view_bottle_{bottle_id}",
                )
            ]
        )
    try:
        if file_id and media_type:
            match media_type:
                case enums.MessageMediaType.PHOTO.name:
                    await client.send_photo(
                        chat_id=sender_id,
                        photo=file_id,
                        caption=reply_content[:1024],
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
                case enums.MessageMediaType.VIDEO.name:
                    await client.send_video(
                        chat_id=sender_id,
                        video=file_id,
                        caption=reply_content[:1024],
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
                case enums.MessageMediaType.AUDIO.name:
                    await client.send_audio(
                        chat_id=sender_id,
                        audio=file_id,
                        caption=reply_content[:1024],
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
                case enums.MessageMediaType.DOCUMENT.name:
                    await client.send_document(
                        chat_id=sender_id,
                        document=file_id,
                        caption=reply_content[:1024],
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
                case enums.MessageMediaType.ANIMATION.name:
                    await client.send_animation(
                        chat_id=sender_id,
                        animation=file_id,
                        caption=reply_content[:1024],
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
                case _:
                    await client.send_message(
                        chat_id=sender_id,
                        text=reply_content,
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=types.InlineKeyboardMarkup(buttons),
                    )
        else:
            await client.send_message(
                chat_id=sender_id,
                text=reply_content,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=types.InlineKeyboardMarkup(buttons),
            )
        await message.reply_text(i18n.t("bot.msg.bottle.reply_sent", locale=lang))
    except Exception as e:
        logger.exception(f"Failed to send reply notification: {e}")
        await message.reply_text(i18n.t("bot.msg.bottle.reply_failed", locale=lang))
        return

    original_user_id = bottle_data.get("user_id")
    original_is_owner = bottle_data.get("is_owner")
    original_lang = bottle_data.get("lang")
    original_text = bottle_data.get("text")
    original_file_id = bottle_data.get("file_id")
    original_media_type = bottle_data.get("media_type")

    row1 = [
        types.InlineKeyboardButton(
            i18n.t("bot.button.bottle.throw_back", locale=original_lang),
            callback_data=f"throw_back {original_user_id}",
        ),
    ]
    if original_is_owner:
        row1.append(
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.destroy", locale=original_lang),
                callback_data=f"destroy_bottle {bottle_id} {original_user_id}",
            )
        )
    else:
        row1.append(
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.reply", locale=original_lang),
                callback_data=f"reply_bottle_menu {bottle_id} {original_user_id}",
            )
        )
    restored_buttons = [
        row1,
        [
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.report", locale=original_lang),
                callback_data=f"report_bottle {bottle_id}",
            ),
            types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.seek", locale=original_lang),
                url=f"https://t.me/{bot_username}?start=seek_bottle_{bottle_id}",
            )
            if bot_username
            else types.InlineKeyboardButton(
                i18n.t("bot.button.bottle.seek", locale=original_lang),
                callback_data="seek_bottle_disabled",
            ),
        ],
    ]
    try:
        if original_media_type and original_file_id:
            if original_text:
                caption = original_text[:1024]
            else:
                caption = None
            match original_media_type:
                case enums.MessageMediaType.PHOTO.name:
                    await reply_to.edit_media(
                        media=types.InputMediaPhoto(
                            original_file_id, caption=caption, has_spoiler=True
                        ),
                        reply_markup=types.InlineKeyboardMarkup(restored_buttons),
                    )
                case enums.MessageMediaType.VIDEO.name:
                    await reply_to.edit_media(
                        media=types.InputMediaVideo(
                            original_file_id, caption=caption, has_spoiler=True
                        ),
                        reply_markup=types.InlineKeyboardMarkup(restored_buttons),
                    )
                case enums.MessageMediaType.AUDIO.name:
                    await reply_to.edit_media(
                        media=types.InputMediaAudio(original_file_id, caption=caption),
                        reply_markup=types.InlineKeyboardMarkup(restored_buttons),
                    )
                case enums.MessageMediaType.DOCUMENT.name:
                    await reply_to.edit_media(
                        media=types.InputMediaDocument(
                            original_file_id, caption=caption
                        ),
                        reply_markup=types.InlineKeyboardMarkup(restored_buttons),
                    )
                case enums.MessageMediaType.ANIMATION.name:
                    await reply_to.edit_media(
                        media=types.InputMediaAnimation(
                            original_file_id, caption=caption, has_spoiler=True
                        ),
                        reply_markup=types.InlineKeyboardMarkup(restored_buttons),
                    )
        elif original_text:
            await reply_to.edit_text(
                original_text,
                reply_markup=types.InlineKeyboardMarkup(restored_buttons),
            )
    except Exception as e:
        logger.error(f"Failed to restore bottle message: {e.__class__.__name__} - {e}")


@Client.on_callback_query(filters.regex(r"^reply_destroy_bottle"), group=0)
async def handle_reply_destroy_bottle_callback(
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
        logger.exception(f"Failed to delete bottle: {e}")
        await callback_query.answer(
            i18n.t("bot.msg.bottle.destroy_failed", locale=lang),
            show_alert=True,
        )
        return
    if callback_query.message:
        await callback_query.edit_message_text(
            i18n.t("bot.msg.bottle.bottle_destroyed", locale=lang)
        )
    else:
        await callback_query.answer(
            i18n.t("bot.msg.bottle.bottle_destroyed", locale=lang)
        )


@Client.on_callback_query(filters.regex(r"^reply_keep_bottle"), group=0)
async def handle_reply_keep_bottle_callback(
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
    if callback_query.message:
        await callback_query.edit_message_text(
            i18n.t("bot.msg.bottle.bottle_kept", locale=lang)
        )
    else:
        await callback_query.answer(i18n.t("bot.msg.bottle.bottle_kept", locale=lang))


@Client.on_message(filters.command("banseapest"), group=0)
async def ban_sea_pest(client: Client, message: types.Message):
    user = message.from_user
    if not user or not user.id:
        return
    db_user = await database.get_user_by_id(user.id)
    if not db_user or not db_user.is_bot_global_admin:
        await message.reply_text(
            i18n.t("bot.msg.bottle.ban_no_permission", locale="zh-CN")
        )
        return
    if not message.command or len(message.command) < 2:
        await message.reply_text("用法: /banseapest <user_id> [天数]")
        return
    try:
        target_user_id = int(message.command[1])
        days = int(message.command[2]) if len(message.command) > 2 else 97
    except ValueError:
        await message.reply_text("用户ID和天数必须是数字")
        return
    count = await database.delete_bottles_by_sender(target_user_id)
    await memttlcache.set(
        f"{_BOTTLE_BAN_PREFIX}{target_user_id}", True, ttl=days * 86400
    )
    await message.reply_text(
        i18n.t("bot.msg.bottle.ban_success", locale="zh-CN").format(
            user_id=target_user_id, count=count
        )
    )
