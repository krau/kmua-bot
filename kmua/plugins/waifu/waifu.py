import html
from io import BytesIO
import pyrogram
from kmua import database, i18n
from kmua import common
from kmua.database.models import ChatData, UserData
from kmua.logger import logger
from . import utils


@pyrogram.Client.on_message(
    pyrogram.filters.command("waifu") & pyrogram.filters.group, group=0
)
async def today_waifu(client: pyrogram.Client, message: pyrogram.types.Message):
    raw_user = message.sender_chat or message.from_user
    raw_chat = message.chat
    chat_config = await database.get_chat_config(raw_chat)
    if not chat_config.waifu_enabled:
        await message.reply(
            text=i18n.t("bot.msg.waifu.disabled", locale=chat_config.lang)
        )
        return
    lock_key = utils.waifu_waiting_key(raw_user.id, raw_chat.id)
    if await common.memstore.get(lock_key):
        return
    await common.memstore.set(lock_key, True)
    waifu: UserData | None = None
    user: UserData = await database.upsert_user(raw_user)
    chat: ChatData = await database.upsert_chat(raw_chat)
    try:
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
        photo = waifu.avatar_big_id or waifu.avatar_big_blob
        if not photo:
            photo = await common.get_big_avatar_bytes(waifu.id)
        if not photo:
            await message.reply_text(
                text=text,
                reply_markup=waifu_markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            return
        try:
            msg = await message.reply_photo(
                photo=BytesIO(photo) if isinstance(photo, bytes) else photo,
                caption=text,
                reply_markup=waifu_markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            await database.update_user_avatar(waifu.id, avatar_big_id=msg.photo.file_id)
        except pyrogram.errors.BadRequest as e:
            logger.error(f"failed to send photo in chat {raw_chat.id}: {e})")
            await message.reply_text(
                text=text,
                reply_markup=waifu_markup,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
    finally:
        await common.memstore.delete(lock_key)
        if waifu and not waifu.avatar_big_blob:
            small_avatar = await common.get_small_avatar_bytes(waifu.id)
            if small_avatar:
                await database.update_user_avatar(
                    waifu.id, avatar_small_blob=small_avatar
                )


@pyrogram.Client.on_message(
    pyrogram.filters.command("waifu_graph") & pyrogram.filters.group, group=0
)
async def waifu_graph(client: pyrogram.Client, message: pyrogram.types.Message):
    raise NotImplementedError


@pyrogram.Client.on_callback_query(pyrogram.filters.regex(r"^remove_waifu"), group=0)
async def remove_waifu(client: pyrogram.Client, query: pyrogram.types.CallbackQuery):
    chat = query.message.chat
    user = query.from_user
    if not await common.can_user_manage_bot_in_chat(user, chat):
        user_config = await database.get_user_config(user)
        await query.answer(
            text=i18n.t("bot.msg.no_permission_group", locale=user_config.lang),
            show_alert=True,
            cache_time=10,
        )
        return
    db_chat = await database.get_chat_by_id(chat.id)
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    data = query.data.split(" ")
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
                reply_markup=None,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        else:
            await query.message.edit_text(
                text=text,
                reply_markup=None,
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
        return

    markup = utils.remove_markup(waifu_id, user_id, lang=lang)

    if data[0].endswith("cancel"):
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
