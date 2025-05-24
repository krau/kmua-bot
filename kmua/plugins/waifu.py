import html
from io import BytesIO
import pyrogram
import pyrogram.errors
from kmua import database, i18n
from kmua import common
from kmua.database.models import ChatData, UserData
from kmua.logger import logger


def _waifu_waiting_key(user_id: int, chat_id: int) -> str:
    return f"user:{user_id}:chat:{chat_id}:waifu:waiting"


def _waifu_markup(
    waifu_id: int, user_id: int, lang: str
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove", locale=lang),
                    callback_data=f"remove_waifu {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.marry", locale=lang),
                    callback_data=f"marry_waifu {waifu_id} {user_id}",
                ),
            ]
        ]
    )


async def _waifu_text(
    waifu: UserData, is_got: bool, user: UserData | None = None, lang: str = "zh-CN"
) -> str:
    if waifu.waifu_mention or not waifu.is_real_user:
        waifu_text = await common.mention_html(waifu)
    else:
        waifu_text = html.escape(waifu.full_name)

    template_key = "bot.msg.waifu."
    if user:
        template_key += "got" if is_got else "normal"
        user_text = await common.mention_html(user)
        return i18n.t(template_key, locale=lang).format(
            user=user_text, waifu=waifu_text
        )
    else:
        template_key += "got_nouser" if is_got else "normal_nouser"
        return i18n.t(template_key, locale=lang).format(waifu=waifu_text)


async def _get_waifu_for_user(
    user: UserData, chat: ChatData
) -> tuple[UserData | None, bool]:
    """get or take waifu for user in chat

    Returns:
        - UserData | None: waifu
        - bool: is_got
    """
    is_got = await database.is_setted_waifu_in_chat(user, chat)
    waifu, _ = await database.get_user_waifu_in_chat(user, chat)
    if waifu:
        return waifu, is_got
    waifu = await database.take_waifu_for_user_in_chat(user, chat)
    if not waifu:
        return None, is_got
    return waifu, is_got


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
    lock_key = _waifu_waiting_key(raw_user.id, raw_chat.id)
    if await common.memstore.get(lock_key):
        return
    await common.memstore.set(lock_key, True)
    waifu: UserData | None = None
    user: UserData = await database.upsert_user(raw_user)
    chat: ChatData = await database.upsert_chat(raw_chat)
    try:
        await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
        waifu, is_got = await _get_waifu_for_user(user, chat)
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
        waifu_markup = _waifu_markup(waifu.id, user.id, chat_config.lang)
        text = await _waifu_text(waifu, is_got, user, lang=chat_config.lang)
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
                photo=BytesIO(photo),
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
