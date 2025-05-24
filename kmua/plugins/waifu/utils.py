import html
import pyrogram
from kmua import database, i18n
from kmua import common
from kmua.database.models import ChatData, UserData


def waifu_waiting_key(user_id: int, chat_id: int) -> str:
    return f"user:{user_id}:chat:{chat_id}:waifu:waiting"


def waifu_markup(
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


async def waifu_text(
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


async def get_waifu_for_user(
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


def remove_markup(
    waifu_id: int, user_id: int, lang: str = "zh-CN"
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove_confirm", locale=lang),
                    callback_data=f"remove_waifu_confirm {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove_cancel", locale=lang),
                    callback_data=f"remove_waifu_cancel {waifu_id} {user_id}",
                ),
            ]
        ]
    )


def marry_markup(
    waifu_id: int, user_id: int, lang: str = "zh-CN"
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.agree_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_agree {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.refuse_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_refuse {waifu_id} {user_id}",
                ),
            ],
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.cancel_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_cancel {waifu_id} {user_id}",
                )
            ],
        ]
    )
